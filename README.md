Aqui está uma sugestão de `README.md` bem completo e didático. Ele não só explica o que o projeto faz, mas também serve como um manual rápido para você ou para outros professores do Colégio Criarte que forem utilizar o sistema no futuro.

Você pode copiar o texto abaixo e salvar como `README.md` na raiz da pasta do seu projeto.

---

# 📝 Escola Analítica: ProvaOps - Embaralhador

**ProvaOps** é um webapp desenvolvido em Python e Streamlit desenhado para automatizar a geração de provas alternativas (Tipos B e C) a partir de um arquivo LaTeX original (Tipo A).

O sistema foi pensado para o fluxo de trabalho de professores e editores que utilizam o Overleaf. Ele resolve o problema de criar provas com questões e alternativas embaralhadas, mantendo a integridade estrutural da avaliação (separação por disciplinas) e preservando o vínculo de textos de apoio com suas respectivas questões.

## ✨ Funcionalidades

* **Embaralhamento Inteligente:** Altera a ordem das questões dentro de cada disciplina e a ordem das alternativas (a, b, c, d, e) dentro de cada questão.
* **Preservação de Blocos:** Garante que textos longos de leitura ("Textos de Apoio") nunca sejam separados das questões que se referem a eles.
* **Mapeamento de Gabarito:** Rastreia para onde a alternativa correta foi movida e gera gabaritos automáticos de conferência.
* **Geração em Lote (Exportação Zip):** Gera duas versões diferentes (B e C) simultaneamente, entregando os códigos LaTeX e os gabaritos em `.csv` compactados em um único arquivo `.zip`.

## ⚙️ Como Preparar o seu Arquivo LaTeX

Para que o motor de embaralhamento leia sua prova corretamente, o arquivo `.tex` original precisa de **três marcações simples** através de comentários e seções:

### 1. Separação de Disciplinas

Antes da primeira questão de uma matéria nova, insira o comando de seção com a tag `DISCIPLINA:` em maiúsculas:

```latex
\section*{DISCIPLINA: Matemática}

```

### 2. Gabarito da Questão

Logo após o texto da alternativa correta, dentro do ambiente `\begin{enumerate}`, adicione o comentário `%CORRETO` (o sistema também aceita variações como `% CORRETA` ou `%CERTA`):

```latex
\begin{enumerate}[(a)]
    \item 42.
    \item 54.
    \item 98. %CORRETO
    \item 110.
    \item 122.
\end{enumerate}

```

### 3. Textos de Apoio (Blocos Indissociáveis)

Se houver um texto que serve de base para uma ou mais questões, "abrace" o texto e as questões com as tags `% INICIO BLOCO` e `% FIM BLOCO`. Assim, elas serão embaralhadas juntas pela prova, sem se separarem:

```latex
% INICIO BLOCO
TEXTO PARA AS QUESTÕES 1, 2 e 3.
(Parágrafos do texto...)

\section*{Questão 1}
...
\section*{Questão 2}
...
\section*{Questão 3}
...
% FIM BLOCO

```

## 🚀 Como Usar o Sistema

### Fluxo de Trabalho (Overleaf -> ProvaOps -> Overleaf)

1. Crie a sua prova principal (Tipo A) no Overleaf com todas as imagens e formatações.
2. Copie todo o código-fonte do arquivo `main.tex`.
3. Abra o app **ProvaOps** e cole o código no campo de texto.
4. Clique em **"Gerar Provas B e C (.zip)"**.
5. Extraia o arquivo baixado. Você terá duas pastas (Prova_B e Prova_C), cada uma contendo um `.tex` e um gabarito `.csv`.
6. Volte ao seu projeto no Overleaf, faça o upload dos arquivos `main_B.tex` e `main_C.tex` na mesma pasta do arquivo original e recompile o PDF. As imagens e formatações serão puxadas automaticamente!

## 💻 Instalação e Execução Local

Se precisar rodar o projeto localmente na sua máquina (Linux Mint/Ubuntu, etc.), siga os passos:

1. Abra o terminal e navegue até a pasta do projeto.
2. Crie e ative um ambiente virtual limpo (para evitar o erro de `externally-managed-environment` do Linux):

```bash
python3 -m venv venv
source venv/bin/activate

```

3. Instale as dependências necessárias:

```bash
pip install streamlit pandas

```

4. Execute o aplicativo:

```bash
streamlit run app.py

```

O sistema abrirá automaticamente no seu navegador padrão.

---

*Desenvolvido para otimizar o fluxo de avaliações do Colégio Criarte com o uso de Data Science e automação em Python.*
