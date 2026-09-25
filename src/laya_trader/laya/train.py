from __future__ import annotations

import argparse
import json
import math
import os
import random
import time
from pathlib import Path

import laya
import numpy as np
import torch
from laya.common import collate_items, proper_reward
from safetensors.torch import save_file
from torch.nn.parallel import DistributedDataParallel as DDP
from torch.utils.data import DataLoader, DistributedSampler, RandomSampler

from laya_trader.laya.records import JsonlDecisionDataset
from laya_trader.progress import ProgressReporter, log_progress


def _dist_setup() -> tuple[int, int, int]:
    world = int(os.environ.get("WORLD_SIZE", "1"))
    rank = int(os.environ.get("RANK", "0"))
    local_rank = int(os.environ.get("LOCAL_RANK", "0"))
    if world > 1:
        torch.distributed.init_process_group(backend="nccl")
        torch.cuda.set_device(local_rank)
    return world, rank, local_rank


def _seed_everything(seed: int, rank: int) -> None:
    seed = seed + rank
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def _to_cpu(value):
    if torch.is_tensor(value):
        return value.detach().cpu()
    if isinstance(value, dict):
        return {key: _to_cpu(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_cpu(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_to_cpu(item) for item in value)
    return value


def _rng_state() -> dict:
    return {
        "python": random.getstate(),
        "numpy": np.random.get_state(),
        "torch": torch.get_rng_state(),
        "cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None,
    }


def _restore_rng_state(state: dict) -> None:
    random.setstate(state["python"])
    np.random.set_state(state["numpy"])
    torch.set_rng_state(state["torch"])
    if state.get("cuda") is not None and torch.cuda.is_available():
        torch.cuda.set_rng_state_all(state["cuda"])


def _save_resume_checkpoint(
    output: Path,
    model,
    optimizer: torch.optim.Optimizer,
    scheduler: torch.optim.lr_scheduler.LRScheduler,
    scaler: torch.cuda.amp.GradScaler,
    epoch: int,
    step: int,
    update: int,
    args: argparse.Namespace,
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    checkpoint = {
        "version": 1,
        "model": {key: value.detach().cpu() for key, value in model.state_dict().items()},
        "optimizer": _to_cpu(optimizer.state_dict()),
        "scheduler": scheduler.state_dict(),
        "scaler": scaler.state_dict(),
        "epoch": epoch,
        "step": step,
        "update": update,
        "args": vars(args),
        "rng": _rng_state(),
    }
    temporary = output / "resume.pt.tmp"
    target = output / "resume.pt"
    torch.save(checkpoint, temporary)
    temporary.replace(target)


def _save_checkpoint(output: Path, model, tokenizer, cfg: dict) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "encoder").mkdir(exist_ok=True)
    (output / "tokenizer").mkdir(exist_ok=True)
    model.encoder.config.save_pretrained(output / "encoder")
    tokenizer.save_pretrained(output / "tokenizer")

    clean_cfg = dict(cfg)
    clean_cfg["temperature"] = [1.0, 1.0, 1.0]
    clean_cfg["temperature_by_options"] = {}
    (output / "rl_agent_config.json").write_text(
        json.dumps(clean_cfg, indent=2), encoding="utf-8"
    )

    state = {k: v.detach().cpu().contiguous() for k, v in model.state_dict().items()}
    save_file(state, str(output / "model.safetensors"))


def train(args: argparse.Namespace) -> None:
    world, rank, local_rank = _dist_setup()
    _seed_everything(args.seed, rank)
    if not torch.cuda.is_available():
        raise RuntimeError("training requires CUDA; use a T4/Ampere-or-newer GPU")
    device = torch.device("cuda", local_rank)
    if rank == 0:
        log_progress("train setup", f"GPU={torch.cuda.get_device_name(device)} loading {args.base_model}")

    agent = laya.load(args.base_model, device="cpu")
    tokenizer = agent.tok
    cfg = dict(agent.cfg)
    cfg["max_len"] = args.max_len
    cfg["head_max_len"] = args.head_max_len
    model = agent.model.to(device).train()
    if args.gradient_checkpointing:
        if not hasattr(model.encoder, "gradient_checkpointing_enable"):
            raise RuntimeError("the selected encoder does not support gradient checkpointing")
        model.encoder.gradient_checkpointing_enable()

    if rank == 0:
        log_progress("train setup", f"model loaded; indexing {args.train}")
    dataset = JsonlDecisionDataset(args.train, tokenizer, args.max_len, args.head_max_len)
    if not len(dataset):
        raise ValueError(f"no records in {args.train}")
    if rank == 0:
        log_progress("train setup", f"indexed {len(dataset)} records")

    def make_loader(epoch: int):
        if world > 1:
            sampler = DistributedSampler(
                dataset, num_replicas=world, rank=rank, shuffle=True, seed=args.seed
            )
            sampler.set_epoch(epoch)
        else:
            generator = torch.Generator()
            generator.manual_seed(args.seed + epoch)
            sampler = RandomSampler(dataset, generator=generator)
        loader = DataLoader(
            dataset,
            batch_size=args.batch_size,
            sampler=sampler,
            num_workers=0,
            collate_fn=lambda batch: collate_items(batch, tokenizer.pad_token_id),
            pin_memory=True,
        )
        return sampler, loader

    _, first_loader = make_loader(0)

    encoder_params = list(model.encoder.parameters())
    encoder_ids = {id(p) for p in encoder_params}
    head_params = [p for p in model.parameters() if id(p) not in encoder_ids]
    optimizer = torch.optim.AdamW(
        [
            {"params": encoder_params, "lr": args.encoder_lr},
            {"params": head_params, "lr": args.head_lr},
        ],
        weight_decay=args.weight_decay,
    )

    updates_per_epoch = math.ceil(len(first_loader) / args.grad_accum)
    total_updates = max(1, updates_per_epoch * args.epochs)
    warmup = max(1, int(total_updates * args.warmup_ratio))

    def lr_lambda(step: int) -> float:
        if step < warmup:
            return max(step, 1) / warmup
        progress = (step - warmup) / max(1, total_updates - warmup)
        return 0.5 * (1.0 + math.cos(math.pi * min(progress, 1.0)))

    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lr_lambda)
    scaler = torch.cuda.amp.GradScaler(enabled=args.amp == "fp16")
    amp_dtype = torch.float16 if args.amp == "fp16" else torch.bfloat16

    if world > 1:
        model = DDP(
            model,
            device_ids=[local_rank],
            output_device=local_rank,
            find_unused_parameters=True,
        )

    start_epoch = 0
    start_step = 0
    update = 0
    if args.resume:
        resume_path = Path(args.resume)
        if not resume_path.is_file():
            raise FileNotFoundError(f"resume checkpoint not found: {resume_path}")
        if rank == 0:
            log_progress("train resume", f"loading {resume_path}")
        resume_state = torch.load(resume_path, map_location="cpu", weights_only=False)
        raw_model = model.module if isinstance(model, DDP) else model
        raw_model.load_state_dict(resume_state["model"])
        optimizer.load_state_dict(resume_state["optimizer"])
        scheduler.load_state_dict(resume_state["scheduler"])
        if resume_state.get("scaler"):
            scaler.load_state_dict(resume_state["scaler"])
        start_epoch = int(resume_state["epoch"])
        start_step = int(resume_state["step"])
        update = int(resume_state["update"])
        _restore_rng_state(resume_state["rng"])
        if rank == 0:
            log_progress(
                "train resume",
                f"resumed from {resume_path} at epoch={start_epoch + 1} "
                f"step={start_step} update={update}",
            )

    progress = None
    optimizer.zero_grad(set_to_none=True)
    for epoch in range(start_epoch, args.epochs):
        _, loader = make_loader(epoch)
        skip_steps = start_step if epoch == start_epoch else 0
        start_step = 0
        if rank == 0:
            log_progress("train", f"epoch={epoch + 1}/{args.epochs} batches={len(loader)}")
        skip_progress = (
            ProgressReporter("train resume skip", skip_steps, unit="batches")
            if rank == 0 and skip_steps else None
        )
        running = 0.0
        running_batches = 0
        for step, batch in enumerate(loader):
            if step < skip_steps:
                if skip_progress is not None:
                    skip_progress.update(step + 1)
                continue
            if progress is None and rank == 0:
                progress = ProgressReporter(
                    "train", total_updates, unit="updates", initial_done=update
                )
            if batch is None:
                continue
            tensors = {
                k: v.to(device, non_blocking=True)
                for k, v in batch.items()
                if torch.is_tensor(v)
            }
            with torch.autocast(device_type="cuda", dtype=amp_dtype, enabled=True):
                logits, _ = model(
                    tensors["input_ids"],
                    tensors["attention_mask"],
                    tensors["marker_pos"],
                    tensors["marker_mask"],
                    tensors["qtype"],
                )
                logp = torch.log_softmax(logits, dim=-1)
                ce = -(tensors["target"] * logp).sum(dim=-1).mean()
                probs = torch.softmax(logits, dim=-1)
                reward = proper_reward(
                    probs,
                    tensors["target"],
                    tensors["qtype"],
                    tensors["marker_mask"],
                    w_sph=0.75,
                ).mean()
                loss = (ce - args.proper_weight * reward) / args.grad_accum

            if scaler.is_enabled():
                scaler.scale(loss).backward()
            else:
                loss.backward()
            running += float(loss.detach()) * args.grad_accum
            running_batches += 1

            do_update = (step + 1) % args.grad_accum == 0 or (step + 1) == len(loader)
            if do_update:
                if scaler.is_enabled():
                    scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), args.max_grad_norm)
                if scaler.is_enabled():
                    scaler.step(optimizer)
                    scaler.update()
                else:
                    optimizer.step()
                optimizer.zero_grad(set_to_none=True)
                scheduler.step()
                update += 1
                if progress is not None:
                    progress.update(
                        update,
                        force=args.log_every > 0 and update % args.log_every == 0,
                        detail=(
                            f"epoch={epoch + 1}/{args.epochs} "
                            f"loss={running / max(1, running_batches):.5f} "
                            f"lr={scheduler.get_last_lr()[0]:.2e}"
                        ),
                    )
                if args.log_every > 0 and update % args.log_every == 0:
                    running = 0.0
                    running_batches = 0
                next_epoch = epoch
                next_step = step + 1
                if next_step >= len(loader):
                    next_epoch += 1
                    next_step = 0
                if rank == 0 and args.checkpoint_every > 0 and update % args.checkpoint_every == 0:
                    raw_model = model.module if isinstance(model, DDP) else model
                    save_started = time.monotonic()
                    log_progress("train checkpoint", f"writing {Path(args.output) / 'resume.pt'} at update={update}")
                    _save_resume_checkpoint(
                        Path(args.output),
                        raw_model,
                        optimizer,
                        scheduler,
                        scaler,
                        next_epoch,
                        next_step,
                        update,
                        args,
                    )
                    log_progress(
                        "train checkpoint",
                        f"saved update={update} next_epoch={next_epoch + 1} "
                        f"next_step={next_step} "
                        f"size_gib={(Path(args.output) / 'resume.pt').stat().st_size / 1024**3:.2f} "
                        f"elapsed={time.monotonic() - save_started:.1f}s",
                    )

        if progress is not None:
            progress.update(update, detail=f"completed_epoch={epoch + 1}/{args.epochs}", force=True)
        if rank == 0 and args.checkpoint_every > 0:
            raw_model = model.module if isinstance(model, DDP) else model
            save_started = time.monotonic()
            log_progress("train checkpoint", f"writing end-of-epoch checkpoint for epoch={epoch + 1}")
            _save_resume_checkpoint(
                Path(args.output),
                raw_model,
                optimizer,
                scheduler,
                scaler,
                epoch + 1,
                0,
                update,
                args,
            )
            log_progress(
                "train checkpoint",
                f"saved completed_epoch={epoch + 1} update={update} "
                f"size_gib={(Path(args.output) / 'resume.pt').stat().st_size / 1024**3:.2f} "
                f"elapsed={time.monotonic() - save_started:.1f}s",
            )

    if rank == 0:
        raw_model = model.module if isinstance(model, DDP) else model
        save_started = time.monotonic()
        log_progress("train final", f"writing model to {args.output}")
        _save_checkpoint(Path(args.output), raw_model, tokenizer, cfg)
        log_progress(
            "train final",
            f"saved uncalibrated checkpoint to {args.output} "
            f"size_gib={(Path(args.output) / 'model.safetensors').stat().st_size / 1024**3:.2f} "
            f"elapsed={time.monotonic() - save_started:.1f}s",
        )
        log_progress("train final", "next: run laya-calibrate on the calibration split")

    if world > 1:
        torch.distributed.barrier()
        torch.distributed.destroy_process_group()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Fine-tune Laya on deterministic trading targets")
    p.add_argument("--train", default="data/dataset/train.jsonl")
    p.add_argument("--output", default="checkpoints/laya-trader-v0.1")
    p.add_argument("--base-model", default="convaiinnovations/laya")
    p.add_argument("--epochs", type=int, default=4)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--grad-accum", type=int, default=4)
    p.add_argument("--encoder-lr", type=float, default=2.5e-5)
    p.add_argument("--head-lr", type=float, default=1e-4)
    p.add_argument("--weight-decay", type=float, default=0.01)
    p.add_argument("--warmup-ratio", type=float, default=0.05)
    p.add_argument("--proper-weight", type=float, default=0.15)
    p.add_argument("--max-grad-norm", type=float, default=1.0)
    p.add_argument("--max-len", type=int, default=512)
    p.add_argument("--head-max-len", type=int, default=192)
    p.add_argument("--amp", choices=("fp16", "bf16"), default="fp16")
    p.add_argument("--gradient-checkpointing", action="store_true")
    p.add_argument("--resume", default=None)
    p.add_argument("--checkpoint-every", type=int, default=250)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--log-every", type=int, default=50)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    train(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
