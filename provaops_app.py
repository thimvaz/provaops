import streamlit as st
import pandas as pd
import re
import random
import string
import zipfile
from io import BytesIO
import docx
from docx.oxml.ns import qn

st.set_page_config(page_title="ProvaOps - Sistema de Provas", layout="wide", page_icon="📝")

# ==========================================
# FUNÇÕES DO ACELERADOR (WORD -> LATEX)
# ==========================================

def _extrair_imagens_do_paragrafo(paragrafo, doc_part):
    """
    Retorna uma lista de tuplas (bytes, extensao) para cada imagem embutida
    no parágrafo, na ORDEM em que aparecem no XML — em vez de assumir uma
    numeração sequencial global que pode não bater com a ordem real.
    """
    imagens = []
    # Localiza todos os elementos <a:blip r:embed="rIdN"/> do parágrafo
    for blip in paragrafo._element.iter(qn('a:blip')):
        r_id = blip.get(qn('r:embed'))
        if not r_id:
            continue
        try:
            image_part = doc_part.related_parts[r_id]
        except KeyError:
            continue
        blob = image_part.blob
        # content_type costuma ser algo como "image/png"
        ext = image_part.content_type.split('/')[-1]
        ext = 'jpg' if ext == 'jpeg' else ext
        imagens.append((blob, ext))
    return imagens


def converter_docx_para_latex(docx_file):
    """
    Converte o .docx em LaTeX e retorna também a lista de imagens
    (bytes, extensão) na ordem correta de aparição no texto — resolvendo
    o descompasso entre nome do arquivo extraído e ordem real no documento.
    """
    doc = docx.Document(docx_file)
    doc_part = doc.part

    latex_output = r"""\documentclass[a4paper,10pt]{exam}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[brazil]{babel}
\usepackage{graphicx}
\usepackage[shortlabels]{enumitem}
\usepackage{multicol}

\begin{document}
"""
    # BUGFIX (relatado pela equipe): as regex antigas aceitavam número/letra
    # seguido só de ESPAÇO (`\s`) como marcador. Isso fazia qualquer frase
    # que começasse com um número (data, quantidade, afirmativa numerada
    # "1. A célula...") ou com as palavras "a"/"e" (artigo/conjunção comuns
    # em português) ser lida como início de questão/alternativa. Agora
    # exigimos pontuação real (`.` ou `)`) logo após o número/letra — sem
    # isso, o texto é tratado como prosa normal.
    regex_questao = re.compile(r'^\s*(?:Quest[aã]o\s+)?(\d+)[\.\)]\s*', re.IGNORECASE)
    regex_alternativa = re.compile(r'^\s*([a-eA-E])[\.\)]\s*')

    dentro_enumerate = False
    imagens_ordenadas = []  # lista final (bytes, ext) na ordem de aparição
    ultima_alternativa_aberta = False  # controla continuação multi-linha

    # BUGFIX (achado real da equipe, docx com questões 7-10 perdidas):
    # a trava anterior ("só aceito nova questão se já vi alternativas
    # lettradas") quebrava qualquer prova cujas opções de resposta não
    # tenham letra visível no texto (ex.: opções digitadas soltas, uma
    # por linha, sem "a)"/"b)"). Nessas provas, alternativas_iniciadas
    # nunca vira True, e TODAS as questões depois da primeira eram
    # perdidas — regressão grave.
    #
    # Nova heurística, combinando três sinais (qualquer um libera a
    # aceitação como nova questão):
    #   1) é a primeira questão do documento/disciplina;
    #   2) a questão atual já alcançou alternativas lettradas; ou
    #   3) o número bate exatamente com o esperado (última questão + 1)
    #      E o parágrafo anterior não foi ele mesmo um número rejeitado
    #      (isso evita reincidir no bug das afirmativas numeradas: numa
    #      sequência "1. 2. 3." dentro do enunciado, se o "2." coincidir
    #      com o número esperado da próxima questão, o fato de "1." ter
    #      sido rejeitado logo antes bloqueia a aceitação de "2." também).
    ultima_questao_numero = None
    alternativas_iniciadas = False
    ultimo_foi_rejeitado_como_questao = False

    for para in doc.paragraphs:
        texto = para.text.strip()
        estilo = para.style.name

        # --- Títulos / disciplinas ---
        if estilo.startswith('Heading 1') or estilo.startswith('Título 1') or 'Heading' in estilo:
            if dentro_enumerate:
                latex_output += "\\end{enumerate}\n\n"
                dentro_enumerate = False
            latex_output += f"\n% ==========================================\n"
            latex_output += f"\\section*{{DISCIPLINA: {texto}}}\n"
            latex_output += f"% ==========================================\n"
            ultima_alternativa_aberta = False
            ultima_questao_numero = None
            alternativas_iniciadas = False
            ultimo_foi_rejeitado_como_questao = False
            continue

        # --- Imagens (correspondência exata via r:embed, não numeração cega) ---
        imgs_deste_paragrafo = _extrair_imagens_do_paragrafo(para, doc_part)
        for _blob, ext in imgs_deste_paragrafo:
            idx_img = len(imagens_ordenadas) + 1
            nome_img = f"images/image{idx_img}"
            latex_output += "\\begin{center}\n"
            latex_output += f"    \\includegraphics[width=0.6\\linewidth]{{{nome_img}}}\n"
            latex_output += "\\end{center}\n"
            imagens_ordenadas.append((_blob, ext))

        if not texto:
            continue

        match_q = regex_questao.match(texto)
        match_alt = regex_alternativa.match(texto)

        numero_atual = int(match_q.group(1)) if match_q else None
        numero_esperado = (ultima_questao_numero + 1) if ultima_questao_numero is not None else None

        aceitar_como_nova_questao = bool(match_q) and (
            ultima_questao_numero is None
            or alternativas_iniciadas
            or (not ultimo_foi_rejeitado_como_questao and numero_atual == numero_esperado)
        )

        if aceitar_como_nova_questao:
            if dentro_enumerate:
                latex_output += "\\end{enumerate}\n\n"
                dentro_enumerate = False
            resto_texto = texto[match_q.end():].strip()
            latex_output += f"\\subsection*{{Questão {numero_atual}}}\n"
            if resto_texto:
                latex_output += f"{resto_texto}\n\n"
            ultima_alternativa_aberta = False
            ultima_questao_numero = numero_atual
            alternativas_iniciadas = False
            ultimo_foi_rejeitado_como_questao = False

        elif match_alt:
            if not dentro_enumerate:
                latex_output += "\\begin{enumerate}[(a)]\n"
                dentro_enumerate = True
            resto_texto = texto[match_alt.end():].strip()
            latex_output += f"\\item {resto_texto}\n"
            ultima_alternativa_aberta = True
            alternativas_iniciadas = True
            ultimo_foi_rejeitado_como_questao = False

        elif dentro_enumerate and ultima_alternativa_aberta:
            # BUGFIX: parágrafo dentro de uma lista de alternativas que NÃO
            # começa com "a)"/"b)" etc. — antes isso fechava o enumerate
            # e quebrava a estrutura. Agora é tratado como continuação da
            # última alternativa (ex.: fórmula ou linha extra da mesma opção).
            latex_output += f"{texto}\n"
            ultimo_foi_rejeitado_como_questao = False

        else:
            if dentro_enumerate:
                latex_output += "\\end{enumerate}\n\n"
                dentro_enumerate = False
            latex_output += f"{texto}\n\n"
            ultima_alternativa_aberta = False
            # Guarda se este parágrafo era um número rejeitado como
            # questão, para bloquear coincidências no próximo parágrafo.
            ultimo_foi_rejeitado_como_questao = bool(match_q)

    if dentro_enumerate:
        latex_output += "\\end{enumerate}\n"

    latex_output += "\\end{document}"
    return latex_output, imagens_ordenadas


def processar_acelerador_zip(docx_file_bytes):
    docx_file_bytes.seek(0)
    latex_text, imagens_ordenadas = converter_docx_para_latex(docx_file_bytes)

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as out_zip:
        out_zip.writestr("base.tex", latex_text)
        # BUGFIX: grava cada imagem com o nome EXATO referenciado no .tex
        # (imageN.<ext real>), na ordem de aparição no texto — em vez de
        # confiar na ordem de listagem do zip interno do docx, que pode
        # não bater com a ordem de leitura do documento.
        for idx, (blob, ext) in enumerate(imagens_ordenadas, start=1):
            out_zip.writestr(f"images/image{idx}.{ext}", blob)

    zip_buffer.seek(0)
    return zip_buffer, latex_text


# ==========================================
# FUNÇÕES DO EMBARALHADOR (LATEX -> PROVAS)
# ==========================================

class QuestaoObj:
    def __init__(self, titulo, corpo):
        self.titulo = titulo
        self.corpo = corpo
        self.alternativas = []
        self.gabarito_orig = -1
        self.estilo_alternativa = "(a)"  # bracket do enumitem, ex. "(a)" ou "(A)"


class BlocoObj:
    def __init__(self):
        self.texto_apoio = ""
        self.questoes = []


class DisciplinaObj:
    def __init__(self, nome):
        self.nome = nome
        self.itens = []


def parse_latex_para_objetos(latex_content):
    split_pre = latex_content.split(r'\begin{document}')
    if len(split_pre) < 2:
        return None, [], "Erro: não encontrei \\begin{document} no texto colado.", []

    preambulo = split_pre[0] + r'\begin{document}'
    corpo_rodape = split_pre[1].split(r'\end{document}')
    if len(corpo_rodape) < 2:
        return None, [], "Erro: não encontrei \\end{document} no texto colado.", []
    corpo = corpo_rodape[0]
    rodape = r'\end{document}'

    pattern = r'(\\(?:sub)?section\*\{.*?\}|%\s*INICIO BLOCO|%\s*FIM BLOCO)'
    tokens = re.split(pattern, corpo, flags=re.IGNORECASE)

    # BUGFIX: re.split com grupo de captura pode, em casos extremos (tag
    # sem conteúdo depois, ou documento cortado), gerar uma lista sem o
    # par completo (tag, conteúdo). Isso causava IndexError sem tratamento.
    # Agora garantimos um número par de elementos após o primeiro token.
    if (len(tokens) - 1) % 2 != 0:
        tokens.append("")

    disciplinas = []
    disc_atual = DisciplinaObj("Geral")
    disciplinas.append(disc_atual)

    bloco_atual = None
    questao_atual = None
    texto_buffer = tokens[0]

    for i in range(1, len(tokens), 2):
        tag = tokens[i].strip()
        conteudo = tokens[i + 1] if i + 1 < len(tokens) else ""

        is_section = tag.startswith('\\')
        is_inicio_bloco = "INICIO BLOCO" in tag.upper()
        is_fim_bloco = "FIM BLOCO" in tag.upper()

        if is_inicio_bloco:
            bloco_atual = BlocoObj()
            bloco_atual.texto_apoio = texto_buffer + conteudo
            disc_atual.itens.append(bloco_atual)
            texto_buffer = ""
            questao_atual = None

        elif is_fim_bloco:
            bloco_atual = None
            texto_buffer = conteudo
            questao_atual = None

        elif is_section:
            titulo_limpo = tag.replace(r'\section*{', '').replace(r'\subsection*{', '').replace('}', '').strip()

            if "DISCIPLINA:" in titulo_limpo:
                nome_disc = titulo_limpo.replace("DISCIPLINA:", "").strip()
                disc_atual = DisciplinaObj(nome_disc)
                disciplinas.append(disc_atual)
                bloco_atual = None
                questao_atual = None
                texto_buffer = conteudo

            elif "Questão" in titulo_limpo or "Questao" in titulo_limpo:
                q = QuestaoObj(titulo_limpo, texto_buffer + conteudo)
                texto_buffer = ""
                questao_atual = q
                if bloco_atual is not None:
                    bloco_atual.questoes.append(q)
                else:
                    disc_atual.itens.append(q)

            else:
                texto_buffer += f"\n{tag}\n{conteudo}"
                if questao_atual:
                    questao_atual.corpo += f"\n{tag}\n{conteudo}"
                    texto_buffer = ""

    avisos = []
    for disc in disciplinas:
        for item in disc.itens:
            questoes_para_processar = item.questoes if isinstance(item, BlocoObj) else [item]

            for q in questoes_para_processar:
                # BUGFIX (achado no exemplo real da equipe): captura também
                # o bracket usado no enumerate (ex. "[(a)]" ou "[(A)]"),
                # para reproduzir o mesmo estilo na versão embaralhada —
                # antes, o Embaralhador sempre forçava "(a)" minúsculo,
                # mesmo em provas que usam "(A)" maiúsculo em algumas
                # disciplinas (comum quando a prova mistura estilos).
                enums = list(re.finditer(r'\\begin\{enumerate\}\s*(?:\[(.*?)\])?(.*?)\\end\{enumerate\}', q.corpo, re.DOTALL))
                if enums:
                    ultimo_enum = enums[-1]
                    bracket_original = ultimo_enum.group(1)
                    itens_texto = ultimo_enum.group(2)
                    itens_raw = re.split(r'\\item\s*', itens_texto)

                    if bracket_original:
                        q.estilo_alternativa = bracket_original

                    alternativas_limpas = []
                    idx_correto = -1

                    for idx, it in enumerate([i for i in itens_raw if i.strip()]):
                        it_str = it.strip()
                        match_gabarito = re.search(r'%\s*(CORRETO|CORRETA|CERTA)\b', it_str, re.IGNORECASE)
                        if match_gabarito:
                            idx_correto = idx
                            it_str = it_str.replace(match_gabarito.group(0), '').strip()
                        # BUGFIX CRÍTICO (achado no exemplo real da equipe):
                        # a equipe marca a alternativa correta com \hl{...}
                        # (pacote soul) para revisão visual no Overleaf, além
                        # do comentário %CORRETO. Sem essa remoção, o
                        # destaque amarelo da resposta certa ia direto para
                        # as provas B/C impressas, entregando o gabarito
                        # para o aluno. Agora removemos o \hl{} mantendo só
                        # o texto interno, de qualquer alternativa.
                        it_str = re.sub(r'\\hl\{(.*?)\}', r'\1', it_str, flags=re.DOTALL)
                        alternativas_limpas.append(it_str)

                    q.alternativas = alternativas_limpas
                    q.gabarito_orig = idx_correto
                    q.corpo = q.corpo[:ultimo_enum.start()] + "[[ALTS]]" + q.corpo[ultimo_enum.end():]

                    # BUGFIX: antes, questão sem %CORRETO virava "?" no
                    # gabarito final silenciosamente. Agora isso é reportado
                    # como aviso explícito na interface antes do download.
                    if idx_correto == -1:
                        avisos.append(f"Questão '{q.titulo}' ({disc.nome}) sem %CORRETO identificado.")
                    if len(alternativas_limpas) > 26:
                        avisos.append(f"Questão '{q.titulo}' ({disc.nome}) tem mais de 26 alternativas — gabarito pode não ser representável por letra.")

    disciplinas = [d for d in disciplinas if d.itens]
    return preambulo, disciplinas, rodape, avisos


def gerar_letras(n):
    """
    BUGFIX: a lista original de letras era fixa em 5 posições (a-e).
    Alternativas além da 5ª causavam gabarito "?" sem aviso. Agora
    suportamos até 26 (a-z), cobrindo qualquer caso realista.
    """
    return [f"({c})" for c in string.ascii_lowercase[:max(n, 26)]]


def gerar_latex_embaralhado(preambulo, disciplinas, rodape, seed, sufixo="B"):
    # BUGFIX: usar uma instância local de Random em vez de random.seed()
    # global, evitando efeitos colaterais em qualquer outro uso de `random`
    # no mesmo processo (ex.: se o Streamlit reexecuta funções em paralelo).
    rng = random.Random(seed)

    novo_latex = preambulo + "\n"
    gabarito_final = []

    contador_global = 1
    letras = gerar_letras(26)

    for disc in disciplinas:
        if disc.nome != "Geral":
            novo_latex += f"\n\\section*{{DISCIPLINA: {disc.nome}}}\n"

        itens_shuffled = disc.itens.copy()
        rng.shuffle(itens_shuffled)

        for item in itens_shuffled:
            if isinstance(item, BlocoObj):
                novo_latex += f"\n{item.texto_apoio}\n"
                questoes_do_bloco = item.questoes
            else:
                questoes_do_bloco = [item]

            for q in questoes_do_bloco:
                novo_latex += f"\\subsection*{{Questão {contador_global}}}\n"

                indices = list(range(len(q.alternativas)))
                rng.shuffle(indices)

                # BUGFIX: usa o bracket original desta questão ("(a)" ou
                # "(A)") em vez de forçar sempre minúsculo.
                bloco_alts = f"\\begin{{enumerate}}[{q.estilo_alternativa}]\n"
                nova_resp_correta = "?"
                idx_correto_original = q.gabarito_orig

                for novo_i, original_i in enumerate(indices):
                    txt = q.alternativas[original_i]
                    bloco_alts += f"\\item {txt}\n"
                    if original_i == idx_correto_original and novo_i < len(letras):
                        nova_resp_correta = letras[novo_i].replace('(', '').replace(')', '').upper()

                bloco_alts += "\\end{enumerate}\n"

                if "[[ALTS]]" in q.corpo:
                    texto_final = q.corpo.replace("[[ALTS]]", bloco_alts)
                else:
                    texto_final = q.corpo + "\n" + bloco_alts

                novo_latex += texto_final

                gabarito_final.append({
                    "Disciplina": disc.nome,
                    "Questão Nova": contador_global,
                    "Gabarito": nova_resp_correta,
                    "Origem": q.titulo,
                    "Versão": f"Prova {sufixo}",
                })

                contador_global += 1

    novo_latex += rodape
    return novo_latex, gabarito_final


# ==========================================
# INTERFACE (FRONTEND)
# ==========================================

st.title("🚀 Escola Analítica: ProvaOps")

tab_acelerador, tab_embaralhador = st.tabs(["⚡ 1. Acelerador (Extrair do Word)", "🎲 2. Embaralhador (Gerar Provas B e C)"])

# --- ABA 1: ACELERADOR ---
with tab_acelerador:
    st.header("Conversor Inteligente de Word para LaTeX")
    st.markdown("""
    **Como usar:**
    1. Baixe o documento do Google Docs clicando em `Arquivo > Fazer download > Microsoft Word (.docx)`.
    2. Suba o ficheiro abaixo.
    3. O sistema extrairá **todo o texto base e imagens originais** para você subir no Overleaf!
    """)

    file_docx = st.file_uploader("📂 Faça o upload da Prova em .docx", type=['docx'])

    if file_docx:
        if st.button("⚙️ Processar e Extrair Imagens", type="primary"):
            try:
                zip_buffer, preview_latex = processar_acelerador_zip(file_docx)

                st.success("✅ Conversão e Extração concluídas com sucesso!")
                st.info("💡 **Dica de Ouro:** Extraia o ficheiro .zip abaixo e suba tudo para o seu projeto no Overleaf. Antes de usar o **Embaralhador** (na próxima aba), abra o `base.tex` no Overleaf e adicione as tags `%CORRETO` nas alternativas e `% INICIO/FIM BLOCO` nos textos de apoio.")

                st.download_button(
                    label="📥 Baixar Pacote Base (.zip com imagens)",
                    data=zip_buffer,
                    file_name="Prova_Base_LaTeX.zip",
                    mime="application/zip",
                    use_container_width=True,
                )

                with st.expander("👀 Ver Prévia do Código Gerado"):
                    st.code(preview_latex, language="latex")
            except Exception as e:
                st.error(f"Ocorreu um erro ao processar: {e}")

# --- ABA 2: EMBARALHADOR ---
with tab_embaralhador:
    st.header("Gerador de Versões (B e C)")

    with st.expander("📖 INSTRUÇÕES PARA O EDITOR (Clique para expandir)", expanded=True):
        st.markdown("""
        ### O que fazer com o ficheiro final?
        1. Certifique-se de que a sua **Prova A** no Overleaf já possui as três marcações essenciais:
            * `\\section*{DISCIPLINA: Nome}`
            * `% INICIO BLOCO` e `% FIM BLOCO` nos textos de apoio.
            * `%CORRETO` dentro da alternativa certa.
        2. Cole o código completo dessa Prova A abaixo (ou suba o `.tex`) e clique em Gerar.
        3. Baixe o ficheiro `.zip`, extraia, e suba os ficheiros `main_B.tex` e `main_C.tex` para a mesma pasta da Prova A no Overleaf.
        4. Recompile e pronto!
        """)

    # OTIMIZAÇÃO: além de colar, permite subir o .tex diretamente,
    # reduzindo erros de copiar/colar (acentos, corte de texto etc.)
    tex_upload = st.file_uploader("📂 (Opcional) Suba o ficheiro .tex em vez de colar", type=['tex'])
    texto_default = tex_upload.read().decode('utf-8') if tex_upload else ""

    latex_input = st.text_area("Cole o Código LaTeX da Prova A Original aqui:", value=texto_default, height=300)

    col_seed, col_empty = st.columns([1, 3])
    with col_seed:
        seed_val = st.number_input("Semente Inicial (Seed)", value=42)

    if st.button("🎲 Gerar Provas B e C (.zip)", type="primary"):
        if not latex_input.strip():
            st.warning("⚠️ Por favor, cole o código LaTeX (ou suba o .tex) antes de gerar.")
        else:
            pre, disc_objs, rod, avisos = parse_latex_para_objetos(latex_input)

            if disc_objs:
                # BUGFIX: avisos de gabarito ausente/estrutura suspeita
                # aparecem ANTES do download, para revisão antes de imprimir.
                if avisos:
                    st.warning("⚠️ Atenção antes de baixar:\n\n" + "\n".join(f"- {a}" for a in avisos))

                tex_B, gab_B = gerar_latex_embaralhado(pre, disc_objs, rod, seed_val, "B")
                df_B = pd.DataFrame(gab_B)

                tex_C, gab_C = gerar_latex_embaralhado(pre, disc_objs, rod, seed_val + 10, "C")
                df_C = pd.DataFrame(gab_C)

                st.success("✅ Provas geradas com sucesso!")

                zip_buffer = BytesIO()
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                    zip_file.writestr("Prova_B/main_B.tex", tex_B)
                    zip_file.writestr("Prova_B/Gabarito_B.csv", df_B.to_csv(index=False))
                    zip_file.writestr("Prova_C/main_C.tex", tex_C)
                    zip_file.writestr("Prova_C/Gabarito_C.csv", df_C.to_csv(index=False))

                zip_buffer.seek(0)

                st.download_button(
                    label="📥 Baixar Pacote Completo de Embaralhamento (.zip)",
                    data=zip_buffer,
                    file_name=f"Provas_Embaralhadas_Seed{seed_val}.zip",
                    mime="application/zip",
                    use_container_width=True,
                )

                st.caption("🔍 Pré-visualização do Gabarito B:")
                st.dataframe(df_B, hide_index=True)
            else:
                st.error(f"❌ Não foi possível ler a estrutura da prova. {rod if isinstance(rod, str) and rod.startswith('Erro') else 'Verifique se copiou o código inteiro (incluindo \\begin{document}).'}")
