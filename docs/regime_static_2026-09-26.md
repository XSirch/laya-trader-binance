# Indicadores versus redução constante de exposição

Foram executados 72 replays de referência com escala constante. As escalas foram calculadas apenas pelas exposições alvo de 2022–2023, sem usar retorno: 80,51% para a referência de volatilidade, 62,38% para concordância e 50,46% para o controle combinado. Esses percentuais multiplicam a exposição da carteira original; não representam diretamente a parcela do capital aplicada.

No agregado de janeiro/2024 a setembro/2026, com custo de 0,15% por lado, os seis controles dinâmicos superaram suas respectivas referências constantes em retorno. A vantagem acumulada variou de 1,09 a 8,74 pontos percentuais. Porém, o teste pareado ajustado às seis comparações não apresentou p-valor inferior a 0,05 em nenhum caso. Isso não prova equivalência; indica evidência insuficiente de superioridade nesta análise.

| Controle dinâmico | Vantagem acumulada sobre constante | Diferença na queda máxima | Diferença de retorno em agosto–setembro |
| --- | ---: | ---: | ---: |
| Volatilidade | +1,09 pp | -0,81 pp | -0,38 pp |
| Volatilidade + trailing | +8,74 pp | -0,49 pp | -0,89 pp |
| Concordância | +3,26 pp | +0,57 pp | -0,04 pp |
| Concordância + trailing | +6,64 pp | -2,05 pp | -0,05 pp |
| Combinado | +3,46 pp | -0,01 pp | -0,22 pp |
| Combinado + trailing | +2,53 pp | +0,67 pp | -0,22 pp |

Valores negativos na coluna de queda máxima favorecem o controle dinâmico. Valores negativos na última coluna indicam perda maior que a referência constante. Todas as seis comparações recentes favoreceram a escala constante em retorno. A custo de 0,30% por lado, a vantagem agregada de volatilidade com trailing também se inverteu: -3,40 pontos percentuais frente à referência constante.

Os intervalos individuais de crescimento relativo anualizado para concordância, com e sem trailing, ficaram acima de zero. Eles não são intervalos simultâneos corrigidos pela seleção entre variantes: os p-valores ajustados correspondentes foram 0,136 e 0,459. Não interpretar os intervalos individuais como confirmação depois de múltiplas pesquisas.

A exposição média foi igualada apenas no desenvolvimento. No agregado posterior, a concordância dinâmica teve exposição bruta alvo média de 29,10%, frente a 27,43% da referência constante. O controle combinado teve 23,22%, frente a 22,19%. Portanto, parte da vantagem de retorno pode vir dessa diferença de exposição; o teste não isola perfeitamente a informação dos indicadores. Com trailing, há também interações entre exposição, ativação do stop e reentrada.

Não há justificativa suficiente para promover os novos controles como solução da perda recente. A referência selecionada anteriormente permanece inalterada e a consistência segue não demonstrada. Essa investigação reduz o risco de atribuir à previsão um benefício que pode ser obtido simplesmente diminuindo as posições.

Evidência: `regime_static_2026-09-26.json`. Reprodução: `python -m jev_trader.regime_static`. O relatório registra a escala, diferenças pareadas, exposição média, diagnóstico estatístico e hashes do código e do experimento anterior. Sem novas chamadas ao JEV ou ordens reais.
