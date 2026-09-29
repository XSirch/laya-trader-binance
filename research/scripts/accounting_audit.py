from pathlib import Path
import csv,json,math,hashlib,sys,warnings
warnings.filterwarnings("ignore",category=DeprecationWarning)
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str((ROOT/'research/src').resolve()))
import pandas as pd
import numpy as np
import sklearn
import xgboost
from binance_multistrategy.data import load_dataset
from binance_multistrategy.learning import TrainedGate,prepare_market,code_fingerprint
from binance_multistrategy.simulation import simulate_trade
sys.stdout.reconfigure(encoding='utf-8')
RES=ROOT/'research/results'; OUT=RES/'accounting_audit_2026-09-28'; OUT.mkdir(parents=True,exist_ok=True)
def sha256(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
variants=[('spot_cuda_exploratory','spot'),('usdm_cuda_lowercut','usd_m'),('usdm_cpu_lowercut','usd_m')]
artifacts=[]
for variant,market in variants:
 for fold in ('fold_01','fold_02'):
  base=RES/variant/fold; model_file=base/'training/model.joblib'; eval_file=base/'test/evaluation.json'
  if model_file.exists() and eval_file.exists(): artifacts.append((variant,market,fold,base,model_file,eval_file))
max_end=max(pd.Timestamp(json.loads(x[5].read_text(encoding='utf-8'))['base']['end_exclusive']) for x in artifacts)
ledger=[];funnels=[];models=[];data_sources=[]
for market in ('spot','usd_m'):
 items=[a for a in artifacts if a[1]==market]
 if not items:continue
 dataset=ROOT/'research/data'/('spot_btc_eth_1m' if market=='spot' else 'usdm_btc_eth_1m')
 candles,provenance=load_dataset(dataset,market);candles=candles.loc[candles.open_time<max_end].copy()
 data_sources.append({'market':market,'dataset_manifest_sha256':sha256(dataset/'dataset.json'),'normalized_data_sha256':provenance['data_sha256'],'rows':len(candles),'symbols':sorted(candles.symbol.unique()),'source_receipts':len(provenance.get('receipts',[])),'verified':provenance.get('verified',False)})
 model0=TrainedGate.load(items[0][4]); candidates,arrays=prepare_market(candles,model0.config)
 print(f'DATA_READY market={market} bars={len(candles)} candidates={len(candidates)} sha256={provenance["data_sha256"]}',flush=True)
 for variant,mkt,fold,base,model_path,eval_path in items:
  model=TrainedGate.load(model_path); scored=model.score(candidates); report=json.loads(eval_path.read_text(encoding='utf-8'))
  mid=model.metadata['model_id'];index={}
  for c in scored.to_dict('records'):
   key=(str(c['symbol']),int(c['side']),str(c['strategy']),pd.Timestamp(c['signal_time']))
   if key in index:raise ValueError(f'duplicate candidate key {key}')
   index[key]=c
  models.append({'variant':variant,'fold':fold,'model_id':mid,'model_sha256':sha256(model_path),
   'model_code_sha256':model.metadata.get('code_sha256'),'current_code_fingerprint':code_fingerprint(),
   'ml_backend':model.metadata.get('ml_backend'),'training_device':model.metadata.get('training_device'),
   'model_threshold':model.threshold,'saved_test_threshold':report['base']['threshold'],'dataset_sha256':provenance['data_sha256'],
   'training_report_sha256':sha256(base/'training/training_report.json'),'evaluation_report_sha256':sha256(eval_path),
   'base_trades_sha256':sha256(base/'test/trades.csv'),'stress_trades_sha256':sha256(base/'test/stress_trades.csv'),
   'base_equity_sha256':sha256(base/'test/equity.csv'),'stress_equity_sha256':sha256(base/'test/stress_equity.csv')})
  for cost in ('base','stress'):
   filename='trades.csv' if cost=='base' else 'stress_trades.csv'
   saved=list(csv.DictReader((base/'test'/filename).open(encoding='utf-8',newline=''))); metrics=report[cost]
   start=pd.Timestamp(metrics['start']);end=pd.Timestamp(metrics['end_exclusive']);threshold=float(metrics['threshold'])
   frame=scored.loc[(scored.signal_time>=start)&(scored.signal_time<end)]
   buffer=frame.loc[frame.signal_time>=end-pd.Timedelta(minutes=480)]
   eligible=frame.loc[frame.signal_time<end-pd.Timedelta(minutes=480)]
   ppass=eligible.loc[eligible.probability>=threshold]
   epass=ppass.loc[ppass.expected_r>=model.config.min_expected_r]
   funnel={'model_variant':variant,'model_id':mid,'market':market,'fold':fold,'cost':cost,
    'emitted_candidates_all_history':len(scored),'emitted_inside_test_window':len(frame),'outside_test_window_first_reject':len(scored)-len(frame),
    'last_480m_buffer_first_reject':len(buffer),'after_time_screen':len(eligible),'below_probability_first_reject':len(eligible)-len(ppass),
    'after_probability':len(ppass),'below_expected_r_first_reject':len(ppass)-len(epass),'after_model_screens':len(epass),
    'blocked_by_open_position':0,'simulation_returned_none':0,'outside_execution_bounds':0,'executed_replay':0,
    'saved_trade_count':len(saved),'threshold':threshold,'minimum_expected_r':model.config.min_expected_r}
   ordered=epass.sort_values(['signal_time','probability','expected_r','symbol','strategy'],ascending=[True,False,False,True,True])
   saved_keys={(r['symbol'],int(r['side']),r['strategy'],pd.Timestamp(r['entry_time'])) for r in saved}
   next_free=start;cash=10000.;replay_keys=[]
   for c in ordered.to_dict('records'):
    sigtime=pd.Timestamp(c['signal_time'])
    if sigtime<next_free:funnel['blocked_by_open_position']+=1;continue
    arr=arrays[c['symbol']]
    outcome=simulate_trade(arr,c,model.config,stress=(cost=='stress'),trace=True)
    if outcome is None:funnel['simulation_returned_none']+=1;continue
    entry=pd.Timestamp(arr.time.iloc[outcome.entry_index]);exit_=pd.Timestamp(arr.time.iloc[outcome.exit_index])+pd.Timedelta(minutes=1)
    sigbar=pd.Timestamp(arr.time.iloc[int(c['signal_index'])]);entrybar=pd.Timestamp(arr.time.iloc[int(c['signal_index'])+1])
    if sigbar!=sigtime-pd.Timedelta(minutes=1) or entrybar!=sigtime or entry!=entrybar:
     raise ValueError(f'timestamp alignment: cand={sigtime!r}, signal_bar={sigbar!r}, entry_bar={entrybar!r}, result={entry!r}')
    if entry<start or exit_>end:funnel['outside_execution_bounds']+=1;continue
    key=(c['symbol'],int(c['side']),c['strategy'],entry)
    if key not in saved_keys:raise ValueError(f'replay has no saved trade {variant}/{fold}/{cost}/{key}')
    old=next(r for r in saved if (r['symbol'],int(r['side']),r['strategy'],pd.Timestamp(r['entry_time']))==key)
    fctr=model.config.stress_multiplier if cost=='stress' else 1.
    friction=2*(model.config.fee_bps+model.config.slippage_bps)*fctr/10000
    stop_frac=abs(outcome.entry_price-outcome.initial_stop)/outcome.entry_price
    exposure=min(model.config.max_notional_equity,model.config.risk_fraction/(stop_frac+friction))
    notional=cash*exposure;pnl=notional*outcome.net_return;q=notional/outcome.entry_price
    side=int(c['side']);slip=model.config.slippage_bps*fctr/10000
    ref_entry=float(arr.values['open'][outcome.entry_index]);ref_exit=outcome.exit_price/(1-side*slip)
    gross_ref=side*(ref_exit-ref_entry)*q
    slip_cost=side*((outcome.entry_price-ref_entry)+(ref_exit-outcome.exit_price))*q
    fee=outcome.fee_per_unit*q;funding=outcome.funding_per_unit*q;gross_fill=side*(outcome.exit_price-outcome.entry_price)*q
    recon=gross_ref-slip_cost-fee-funding-pnl
    checks={'entry_fill':outcome.entry_price-float(old['entry_price']),'exit_fill':outcome.exit_price-float(old['exit_price']),
     'net_return':outcome.net_return-float(old['net_return']),'net_r':outcome.net_r-float(old['net_r']),
     'notional':notional-float(old['notional']),'pnl':pnl-float(old['pnl']),'exit_time_seconds':(exit_-pd.Timestamp(old['exit_time'])).total_seconds()}
    if max(abs(x) for x in checks.values())>1e-7 or abs(recon)>1e-7:raise ValueError(f'PnL/cost mismatch {variant}/{fold}/{cost}/{key}: {checks}; recon={recon}')
    equity_before=cash;cash+=pnl;next_free=exit_;replay_keys.append(key)
    distance=abs(outcome.entry_price-outcome.initial_stop);exc=[]
    for j in range(outcome.entry_index,outcome.exit_index+1):
     exc.extend((side*(float(arr.values['high'][j])-outcome.entry_price),side*(float(arr.values['low'][j])-outcome.entry_price)))
    tid=hashlib.sha256(f'{mid}|{fold}|{cost}|{c["symbol"]}|{side}|{c["strategy"]}|{entry.isoformat()}'.encode()).hexdigest()[:24]
    ledger.append({'trade_id':tid,'model_variant':variant,'model_id':mid,'market':market,'fold':fold,'cost':cost,
     'symbol':c['symbol'],'side':side,'strategy':c['strategy'],'regime':int(c['regime']),'probability':float(c['probability']),'expected_r':float(c['expected_r']),
     'signal_bar_open_time':sigbar.isoformat(),'signal_information_available_at':(sigbar+pd.Timedelta(minutes=1)).isoformat(),'entry_time':entry.isoformat(),'exit_time':exit_.isoformat(),
     'entry_reference_open':ref_entry,'entry_fill':outcome.entry_price,'exit_reference_price':ref_exit,'exit_fill':outcome.exit_price,
     'initial_stop':outcome.initial_stop,'final_stop':outcome.final_stop,'target':outcome.target,'exit_reason':outcome.exit_reason,
     'quantity_base_units':q,'initial_notional_usd':notional,'equity_before_usd':equity_before,'equity_after_usd':cash,
     'stop_distance_fraction':stop_frac,'planned_stop_risk_usd':notional*stop_frac,'cost_adjusted_risk_usd':notional*(stop_frac+friction),
     'risk_fraction_config':model.config.risk_fraction,'configured_risk_cap_usd':equity_before*model.config.risk_fraction,
     'max_notional_equity_config':model.config.max_notional_equity,'configured_notional_cap_usd':equity_before*model.config.max_notional_equity,
     'raw_price_pnl_usd':gross_ref,'adverse_slippage_usd':slip_cost,'commission_usd':fee,'funding_cost_signed_usd':funding,
     'fill_price_pnl_before_fee_funding_usd':gross_fill,'net_pnl_usd':pnl,'net_return_on_initial_notional':outcome.net_return,'net_r':outcome.net_r,
     'mfe_r_ohlc_diagnostic':max(exc)/distance,'mae_r_ohlc_diagnostic':min(exc)/distance,'exit_bar_included_in_excursion':True,
     'cost_reconciliation_error_usd':recon,'saved_csv_pnl_error_usd':checks['pnl']})
   if set(replay_keys)!=saved_keys:
    missing=saved_keys-set(replay_keys);extra=set(replay_keys)-saved_keys
    raise ValueError(f'trade-set mismatch {variant}/{fold}/{cost}; missing={len(missing)}, extra={len(extra)}')
   funnel['executed_replay']=len(replay_keys);funnels.append(funnel)
   ev=metrics['mean_net_return']; evtext='n/a' if ev is None else f'{ev:.5%}'
   print(f'REPLAY_OK {variant}/{fold}/{cost}: n={len(replay_keys)} EV={evtext} artifact_threshold={model.threshold} evaluated_threshold={threshold}',flush=True)
def write_csv(path,rows):
 if not rows:raise ValueError(f'empty output {path}')
 with path.open('w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]),extrasaction='raise');w.writeheader();w.writerows(rows)
write_csv(OUT/'trade_cost_decomposition.csv',ledger);write_csv(OUT/'signal_funnel.csv',funnels)
paths=[{k:r[k] for k in ('trade_id','model_variant','market','fold','cost','symbol','side','strategy','signal_bar_open_time','signal_information_available_at','entry_time','exit_time','exit_reason','net_pnl_usd','net_return_on_initial_notional','net_r','mfe_r_ohlc_diagnostic','mae_r_ohlc_diagnostic','exit_bar_included_in_excursion')} for r in ledger]
write_csv(OUT/'path_diagnostics.csv',paths)
summary={'created_utc':pd.Timestamp.now(tz='UTC').isoformat(),'scope':'reconstruct saved test trades and replay frozen model artifacts only; no retraining, tuning, external calls, or live orders.',
 'models':models,'data_sources':data_sources,'trade_rows':len(ledger),'funnel_rows':len(funnels),
 'audit_script_sha256':sha256(__file__),'runtime':{'python':sys.version.split()[0],'numpy':np.__version__,'pandas':pd.__version__,'scikit_learn':sklearn.__version__,'xgboost':xgboost.__version__,'xgboost_use_cuda':xgboost.build_info().get('USE_CUDA',False)},
 'all_saved_trades_reproduced':True,
 'max_abs_cost_reconciliation_error_usd':max(abs(float(r['cost_reconciliation_error_usd'])) for r in ledger),
 'max_abs_saved_csv_pnl_error_usd':max(abs(float(r['saved_csv_pnl_error_usd'])) for r in ledger),
 'maximum_cost_adjusted_risk_over_configured_cap_usd':max(max(0.0,float(r['cost_adjusted_risk_usd'])-float(r['configured_risk_cap_usd'])) for r in ledger),
 'signal_close_to_next_open_timestamps_match':all(r['signal_information_available_at']==r['entry_time'] for r in ledger),
 'all_fill_pnl_and_cost_components_reconciled_within_1e-7_usd':True,
 'interpretation':['signal_time is the completed candle close; the next-open fill has the same timestamp.',
 'MFE/MAE are OHLC extrema through exit candle. Exit-bar values may occur after the fill; diagnostics are not captured PnL.',
 'Funnel is aggregated by model/fold/cost and begins at emitted candidates; it excludes candles rejected before candidate generation.',
 'Historical replay is diagnostic only and does not authorize trading.']}

(OUT/'audit_summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True,allow_nan=False)+'\n',encoding='utf-8')

print('AUDIT_OUTPUT',json.dumps({'trades':len(ledger),'funnels':len(funnels),'files':{p.name:p.stat().st_size for p in OUT.iterdir()}},ensure_ascii=False),flush=True)
