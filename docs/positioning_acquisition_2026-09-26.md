# Aquisição e qualidade dos dados de posicionamento

Concluída a aquisição dos **4.896 arquivos** previstos, com **3.899 resumos utilizáveis** e **997 indisponíveis por qualidade**. Nenhum arquivo terminou com falha de aquisição ou integridade, e nenhum arquivo planejado ficou sem verificação. Esta etapa prepara o comparativo entre sessenta e sessenta e oito campos; não contém retorno de estratégia nem demonstra cumprimento da meta de 50% ao ano com drawdown de 10%.

O código de aquisição foi congelado no commit `0cd0a56`; a integração do comparativo e seus testes, em `aa9046e`. O piloto verificou cem arquivos, dos quais oitenta eram utilizáveis. Os vinte restantes, todos de 31/12/2021, tinham razões vazias nos CSVs. A coleta completa revalidou esse cache e adquiriu os 4.796 arquivos restantes, sempre com até quatro requisições de arquivos simultâneas. A execução completa durou 38,43 minutos. O calendário exclui explicitamente 124 combinações posteriores ao encerramento de contratos; nenhuma foi substituída por um ativo atual.

| Ano | Arquivos verificados | Resumos utilizáveis | Indisponíveis |
|---|---:|---:|---:|
| 2021 | 100 | 80 | 20 |
| 2022 | 1040 | 121 | 919 |
| 2023 | 1040 | 1038 | 2 |
| 2024 | 1040 | 998 | 42 |
| 2025 | 992 | 981 | 11 |
| 2026 | 684 | 681 | 3 |

Foram preservados 55.408.709 bytes de ZIPs e 476.167 bytes de checksums. A verificação offline reabriu os arquivos, conferiu hashes, CRC, esquema e identidade, reproduziu os resumos e confirmou que os bytes existentes não mudaram. O manifesto de todos os registros, fontes e hashes está nos inputs completos ignorados pelo Git; seu digest é `d74e80d6b5b39afb923cba68509dc762db6ee015371ecb2afe3ec2cccab74c82`. A [evidência compacta](positioning_acquisition_2026-09-26.json) guarda totais, detalhes por ativo/ano e hashes dos registros de execução.

A inspeção direta dos 1.040 arquivos de 2022 encontrou 288 horários em todos eles e nenhum zero numérico, mas campos realmente vazios impediram 919 resumos. Apenas seis sextas tiveram todos os vinte ativos utilizáveis, além de uma observação isolada de XLM. Contagens e medianas reproduziram os registros; não foi um erro de agregação. A regra fixa que exige as sextas atual, anterior e quatro semanas antes eliminou a combinação necessária nos cortes de 10/01/2022 a 02/01/2023. Esses dados não serão substituídos por datas posteriores.

A preparação preservou os sessenta indicadores originais e confirmou seu hash `6858c7cf9f86d184fc292095082f5d11c9dfd96b7128eae0d374e53f8ab326e8` contra o experimento anterior. Após acrescentar os oito campos e aplicar os lags, restam **3.565 observações ativo/segunda-feira**, antes dos filtros de liquidez/volatilidade, formação de rótulos e treino mínimo. Há 1.711 observações sem os resumos necessários no histórico original. Os dois modelos usarão exatamente essa mesma disponibilidade; o controle selecionará somente os sessenta campos originais.

As versões foram observadas agora. Fuso UTC e publicação anterior à decisão continuam sendo hipóteses; LastModified não prova primeira publicação, e o atraso de mais de 48 horas não elimina revisões posteriores. Portanto, `historical_point_in_time_verified` permanece falso. A qualidade dos bytes permite estudar a hipótese retrospectivamente, sem afirmar que todas essas versões estavam disponíveis no passado.

A suíte de implementação passou com **394 testes, sem skips**, incluindo paridade exata do controle com a implementação congelada, causalidade dos rótulos, critérios de qualidade e preservação de arquivos divergentes. Nenhuma chamada paga ao JEV, ordem real ou alteração do watcher paper integrou esta aquisição.

O comando `.venv-tree/Scripts/python.exe -m jev_trader.positioning_research --prepare-only` reproduz a preparação sem treinar ou simular uma carteira. O [protocolo pareado](positioning_prediction_protocol_2026-09-26.md) define os trinta e dois cenários antes de seus resultados financeiros.
