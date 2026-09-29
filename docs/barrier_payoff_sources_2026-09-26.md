# Fontes para retorno de uma operação encerrada por barreiras

Consulta em 26/09/2026, antes de qualquer resultado desta hipótese. Esta nota fundamenta a definição do alvo e suas limitações; não apresenta evidência de rentabilidade. Não foram instalados pacotes, baixados dados de mercado, executados modelos ou backtests, nem feitas chamadas JEV.

## Definição autoral e implementação consultada

Marcos López de Prado descreve, em seu próprio site, o método de três barreiras como uma rotulagem supervisionada compatível com uma estratégia previamente definida por realização de lucro, stop e horizonte. Na mesma página, distingue meta-labeling, no qual um segundo algoritmo avalia as apostas de um modelo primário, e relaciona purging/embargo ao vazamento causado por sobreposição dos rótulos. Essa descrição fundamenta a origem conceitual; não especifica parâmetros para BTC ou demonstra a meta local de retorno/risco. [Página do autor: Innovations](https://www.quantresearch.org/Innovations.htm).

O código público de `mlfinpy.labeling.labeling` percorre uma série de fechamentos desde o início de cada evento, identifica o primeiro cruzamento de cada limiar e usa a menor data entre lucro, stop e horizonte. A barreira temporal utiliza o primeiro timestamp disponível igual ou posterior ao prazo. As distâncias horizontais são múltiplos de um alvo fornecido; o código consultado compara cruzamentos estritos. Ele oferece retornos e classes, inclusive a variante que atribui zero ao vencimento temporal. Como recebe uma série `close`, não determina qual extremo ocorreu primeiro dentro de um candle OHLC. [Código publicado pelo projeto Mlfin.py, funções `triple_barriers`, `add_vertical_barrier`, `get_events` e `get_bins`](https://mlfinpy.readthedocs.io/en/stable/_modules/mlfinpy/labeling/labeling.html).

Mlfin.py é uma implementação independente de Robert Bach inspirada no livro. A fonte é primária quanto ao comportamento desse pacote, mas não é código oficial de López de Prado nem foi verificada como reprodução integral do livro. Nenhum código desse pacote foi importado para o estudo. [Apresentação do mantenedor](https://mlfinpy.readthedocs.io/en/latest/About.html).

A documentação do projeto também representa cada rótulo por um intervalo entre início e término. Dois rótulos podem depender dos mesmos retornos quando esses intervalos se sobrepõem. Portanto, contar eventos horários como observações independentes seria uma suposição adicional. [Mlfin.py: Data Sampling](https://mlfinpy.readthedocs.io/en/latest/Sampling.html).

## Adaptação local a registrar no protocolo

As escolhas abaixo pertencem à pesquisa local. Não foram extraídas como receita de rentabilidade das fontes citadas.

| Elemento | Contrato da adaptação |
|---|---|
| Quantidade prevista | Retorno bruto de preço de uma compra encerrada por lucro, stop ou prazo máximo de oito horas: preço de saída simulado dividido pelo preço de entrada, menos um. O tipo de saída e os tempos devem permanecer na auditoria. |
| Modelo | Regressão HGB sobre esse retorno, preservando a magnitude dos resultados. Isso não equivale a classificar diretamente qual barreira será tocada, a meta-labeling de um modelo primário, a estimar quantis ou a fornecer probabilidade calibrada de lucro. |
| Informação de entrada | Na execução em `t`, usar apenas dados encerrados até `t-1h`. Definir as distâncias das barreiras com informação disponível nesse corte; preço de preenchimento não pode ser usado retroativamente como indicador. |
| Ambiguidade OHLC | Um candle de uma hora não revela a ordem entre máxima e mínima. Se ambas as barreiras puderem ser tocadas no mesmo candle, adotar stop primeiro e registrar a colisão. É uma convenção conservadora, não observação do percurso real. |
| Disponibilidade do rótulo | O evento pode terminar durante uma hora, mas a qualidade e os extremos completos do candle de saída só ficam conhecidos em seu fechamento. Usar esse fechamento como disponibilidade mínima e admitir no treino apenas disponibilidade estritamente anterior ao corte da previsão. |
| Custos e decisão | O rótulo bruto não desconta taxas ou deslizamento. O script deve decidir com o critério líquido fixado e contabilizar efetivamente cada preenchimento. A previsão não é retorno líquido de carteira. |

A documentação oficial do HGB distingue `squared_error`, baseada em mínimos quadrados, de `quantile`, que usa perda pinball. A adaptação proposta permanece uma regressão com perda quadrática; a novidade é o retorno definido pelo caminho e pela saída da operação. Não alegar que a troca do alvo remove as limitações de estimar uma média. [scikit-learn: HistGradientBoostingRegressor](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html).

## Limites que continuam abertos

A regra stop primeiro não comprova preenchimento no preço da barreira, não elimina gaps nem garante queda máxima de 10%. Preços de abertura além dos limiares, execução no prazo, colisões, liquidez, custos e observações incompletas precisam de regras explícitas e idênticas entre construção do alvo e replay. O protocolo deve fixá-las antes de calcular resultados.

Exigir rótulos concluídos antes do corte impede usar resultados ainda futuros no ajuste, mas não elimina a dependência entre rótulos de treino sobrepostos. Contabilidade de carteira deve respeitar capital e posições existentes; não somar retornos de entradas hipotéticas sobrepostas como se todos pudessem ser obtidos simultaneamente. Nenhuma das fontes consultadas valida o histórico local, o preenchimento simulado ou a combinação de 50% ao ano com drawdown de até 10%.
