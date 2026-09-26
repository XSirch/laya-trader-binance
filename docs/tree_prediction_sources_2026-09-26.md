# Fontes para previsão com árvores e validação temporal

Consulta em 26/09/2026. Nota metodológica; não constitui resultado de backtest nem evidência de que a meta de 50% ao ano e drawdown de 10% seja atingível. Foram consultadas apenas documentação oficial, código da biblioteca e artigo dos autores.

## Estimador e especificação inicial

`HistGradientBoostingRegressor` permite limitar folhas, profundidade, tamanho mínimo das folhas e número de árvores, além de aplicar regularização L2. Suporta valores ausentes, mas isso não dispensa verificar a disponibilidade histórica de cada indicador. O parâmetro `random_state` inteiro torna a aleatoriedade repetível entre chamadas. A documentação consultada identifica a versão 1.9.1. [API oficial](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html).

Proposta de partida, escolhida por parcimônia e **sem otimização sobre resultados financeiros**:

```python
HistGradientBoostingRegressor(
    loss="squared_error",
    learning_rate=0.05,
    max_iter=100,
    max_leaf_nodes=7,
    max_depth=3,
    min_samples_leaf=100,
    l2_regularization=1.0,
    max_features=1.0,
    max_bins=63,
    categorical_features=None,
    early_stopping=False,
    validation_fraction=None,
    warm_start=False,
    random_state=20260926,
)
```

Esses valores são uma recomendação de desenho experimental, não parâmetros recomendados pela biblioteca para mercados financeiros. O protocolo definitivo deve fixar uma única configuração antes do replay; não acrescentar uma grade de parâmetros depois de observar perdas. Árvores rasas permitem interações entre indicadores com capacidade limitada. `min_samples_leaf=100` pode produzir modelos quase constantes em janelas pequenas; isso deve ser registrado, não corrigido silenciosamente para melhorar retorno.

Para um alvo de retorno esperado com valores positivos e negativos, proponho erro quadrático. Sua minimização estima a média condicional; erro absoluto estima a mediana, que responde a outra pergunta. Essa distinção decorre da definição matemática das perdas, não constitui previsão de lucro. A implementação de erro absoluto atualiza folhas pela mediana dos resíduos e ignora a regularização nessa atualização final. [Código oficial, função `_update_leaves_values`](https://raw.githubusercontent.com/scikit-learn/scikit-learn/1.9.1/sklearn/ensemble/_hist_gradient_boosting/gradient_boosting.py). `gamma` exige alvo estritamente positivo e `poisson` não negativo; não são adequados ao retorno assinado sem reformular o problema. [API oficial](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html).

## O risco do early stopping automático

Com `early_stopping="auto"`, mais de 10.000 linhas ativam a parada antecipada; fornecer validação explícita também a ativa. `X_val` e `y_val` existem desde a versão 1.7. [API oficial](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html). A implementação cria a validação interna com `train_test_split` quando não é fornecida uma separação explícita. [Código oficial](https://raw.githubusercontent.com/scikit-learn/scikit-learn/1.9.1/sklearn/ensemble/_hist_gradient_boosting/gradient_boosting.py). A função usa `shuffle=True` por padrão. [API de `train_test_split`](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.train_test_split.html).

Implicação para este painel: 20 ativos podem ultrapassar 10.000 linhas diárias sem que exista quantidade equivalente de observações temporais independentes. Uma divisão aleatória mistura datas e rótulos sobrepostos. A opção inicial acima desliga esse mecanismo e fixa 100 iterações. Se futuramente houver parada antecipada, sua validação deve ser um bloco cronológico separado dentro do histórico de treinamento, com rótulos já encerrados antes do início da validação. O teste financeiro externo permanece separado.

## Causalidade e amostra

`TimeSeriesSplit` preserva a ordem temporal e oferece `gap`, contado em **amostras**, não em dias. A comparação direta entre suas partições pressupõe amostras igualmente espaçadas. [Documentação oficial](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html).

Aplicação proposta ao painel: dividir por datas únicas e manter todos os ativos da mesma data no mesmo bloco. Não aplicar `gap=7` diretamente a linhas ativo/dia esperando excluir sete dias. Para alvos de sete dias, admitir no treinamento somente observações cujo fim efetivo do rótulo já seja conhecido no corte de previsão; considerar também o atraso de execução. Verificar disponibilidade dos preços necessários ao rótulo, funding, restrições de negociação e dados ausentes. Essas regras são inferências específicas deste projeto a partir da exigência de ordem temporal.

Qualquer normalização, imputação, seleção de indicadores ou transformação aprendida deve ser ajustada apenas no treinamento. Ajustar transformações no conjunto completo permite que informação futura afete o modelo. A documentação recomenda separar os conjuntos antes do ajuste e usar `Pipeline` quando houver pré-processamento aprendido. [Práticas oficiais contra vazamento](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage).

Registrar quantidade de linhas, datas únicas, ativos, início/fim dos rótulos e exclusões por treinamento. O total de linhas não é medida de independência estatística: ativos compartilham movimentos de mercado e alvos de sete dias consecutivos compartilham preços. Limites de amostra, calendário de retreinamento, horizonte e regras de posição devem constar do protocolo anterior aos resultados.

## Reprodutibilidade e dependências

No momento da inspeção local, `.venv` usa Python 3.13.9 e não possui metadados instalados de `numpy`, `scipy`, `scikit-learn`, `joblib`, `threadpoolctl` ou `narwhals`. Verificação por `importlib.metadata.distributions()`, sem instalar pacotes. A fonte oficial da versão 1.9.1 exige Python >=3.11 e declara `numpy>=1.24.1`, `scipy>=1.10.0`, `joblib>=1.4.0`, `narwhals>=2.0.1` e `threadpoolctl>=3.5.0`. [Manifesto oficial 1.9.1](https://raw.githubusercontent.com/scikit-learn/scikit-learn/1.9.1/pyproject.toml).

A documentação recomenda ambiente isolado e distribuição binária de NumPy/SciPy para evitar compilação acidental. [Instalação oficial](https://scikit-learn.org/stable/install.html). Antes do estudo, fixar as versões efetivamente resolvidas e registrar Python, sistema, bibliotecas numéricas e paralelismo; congelar também nomes/ordem dos 60 indicadores, unidades, dados, parâmetros e hashes dos arquivos. Uma semente não substitui esse registro nem garante identidade binária entre ambientes diferentes.

## Interpretação do resultado

Bailey, Borwein, López de Prado e Zhu descrevem como selecionar estratégias entre muitas tentativas pode produzir desempenho histórico atraente sem generalização, e propõem a probabilidade de sobreajuste de backtest. Ressaltam que separar um holdout não elimina a influência do número de tentativas e do conhecimento prévio daquele período. [Artigo original, *The Probability of Backtest Overfitting*](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).

Portanto, este novo modelo deve entrar no inventário acumulado de hipóteses. Históricos já examinados continuam retrospectivos, mesmo com previsão causal. Reportar todos os cenários predefinidos, incluir custos e funding, comparar previsões com referência constante e avaliar a carteira completa. Erro preditivo menor, ajuste técnico correto e um resultado positivo isolado não comprovam retorno anual de 50% com drawdown máximo de 10%.
