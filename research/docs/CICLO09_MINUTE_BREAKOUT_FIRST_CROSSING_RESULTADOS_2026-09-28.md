# Ciclo 09 — implementação do cruzamento sem efeito

O replay foi encerrado em 28/09/2026. O protocolo pretendia exigir que o preço cruzasse o canal; a implementação comparou o fechamento anterior com o canal do candle atual. Como esse canal inclui a máxima/mínima do candle anterior, a comparação não filtrou a permanência fora do canal.

Os arquivos de candidatos e rótulos são byte a byte idênticos aos do C08:

- `candidates.csv`: SHA-256 `939d33fa8cd87141e06958e446efe1bd938dafce5b076841a64e65fa9be7db29` em ambos.
- `candidate_labels.csv`: SHA-256 `243c635c7e33eb04fd8dedd6c06855eaa2740c28dc50e67d0e9aed1709a77c05` em ambos.
- Ambos contêm 15.410 candidatos e 15.393 rótulos.

O script chegou a treinar oito modelos CUDA e simulou o portfólio, mas nenhum resultado de desempenho do C09 é evidência sobre a hipótese de primeiro cruzamento. O mesmo teste foi repetido sem alterar o conjunto de decisões. Os artefatos permanecem preservados para auditoria; a execução é classificada como `invalid_hypothesis_implementation`, sem conclusão favorável ou desfavorável sobre a regra de cruzamento.

## Correção metodológica

O estado anterior deve ser calculado com o canal anterior: fechamento anterior `<= Donchian_high.shift(1)` para long e `>= Donchian_low.shift(1)` para short. O sinal atual ainda exige o fechamento atual fora do canal atual. O Ciclo 10 implementará essa transição, terá teste que reproduz o caso de canal móvel e será preregistrado separadamente. Nenhuma ordem real foi enviada.
