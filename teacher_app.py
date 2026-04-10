import streamlit as st
import pandas as pd
import re
import random
import zipfile
from io import BytesIO
import docx

st.set_page_config(page_title="ProvaOps - Sistema de Provas", layout="wide", page_icon="📝")

# ==========================================
# FUNÇÕES DO ACELERADOR (WORD -> LATEX)
# ==========================================

def converter_docx_para_latex(docx_file):
    doc = docx.Document(docx_file)
    latex_output = r"""\documentclass[a4paper,10pt]{exam}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[brazil]{babel}
\usepackage{graphicx}
\usepackage[shortlabels]{enumitem}
\usepackage{multicol}

\begin{document}
"""
    regex_questao = re.compile(r'^\s*(?:Questão\s+)?(\d+)[\.\)\-\s]+', re.IGNORECASE)
    regex_alternativa = re.compile(r'^\s*([a-eA-E])[\.\)\-\s]+')
    
    dentro_enumerate = False
    contador_imagens = 1
    
    for para in doc.paragraphs:
        texto = para.text.strip()
        estilo = para.style.name
        
        # Detecta Títulos para Disciplinas
        if estilo.startswith('Heading 1') or estilo.startswith('Título 1') or 'Heading' in estilo:
            if dentro_enumerate:
                latex_output += "\\end{enumerate}\n\n"
                dentro_enumerate = False
            latex_output += f"\n% ==========================================\n"
            latex_output += f"\\section*{{DISCIPLINA: {texto}}}\n" 
            latex_output += f"% ==========================================\n"
            continue

        # Detecta Imagens
        if 'graphic' in para._element.xml:
            # Omitimos a extensão (.png/.jpg) propositalmente. O LaTeX auto-detecta a correta!
            nome_img = f"images/image{contador_imagens}" 
            latex_output += "\\begin{center}\n"
            latex_output += f"    \\includegraphics[width=0.6\\linewidth]{{{nome_img}}}\n"
            latex_output += "\\end{center}\n"
            contador_imagens += 1

        if not texto: continue
            
        match_q = regex_questao.match(texto)
        match_alt = regex_alternativa.match(texto)
        
        # É o início de uma questão?
        if match_q:
            if dentro_enumerate:
                latex_output += "\\end{enumerate}\n\n"
                dentro_enumerate = False
            
            num_q = str(int(match_q.group(1)))
            resto_texto = texto[match_q.end():].strip()
            
            latex_output += f"\\subsection*{{Questão {num_q}}}\n"
            if resto_texto:
                latex_output += f"{resto_texto}\n\n"
            
        # É uma alternativa (a, b, c, d, e)?
        elif match_alt:
            if not dentro_enumerate:
                latex_output += "\\begin{enumerate}[(a)]\n"
                dentro_enumerate = True
            resto_texto = texto[match_alt.end():].strip()
            latex_output += f"\\item {resto_texto}\n"
            
        # É texto normal (enunciado ou texto de apoio)
        else:
            if dentro_enumerate: 
                latex_output += "\\end{enumerate}\n\n"
                dentro_enumerate = False
            latex_output += f"{texto}\n\n"

    if dentro_enumerate:
        latex_output += "\\end{enumerate}\n"

    latex_output += "\\end{document}"
    return latex_output

def processar_acelerador_zip(docx_file_bytes):
    docx_file_bytes.seek(0)
    latex_text = converter_docx_para_latex(docx_file_bytes)
    
    docx_file_bytes.seek(0)
    zip_buffer = BytesIO()
    
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as out_zip:
        # Escreve o código base gerado
        out_zip.writestr("base.tex", latex_text)
        
        # Lê o docx como um ZIP oculto e caça a pasta media/
        with zipfile.ZipFile(docx_file_bytes, "r") as in_zip:
            for item in in_zip.namelist():
                if item.startswith("word/media/"):
                    filename = item.split("/")[-1]
                    image_data = in_zip.read(item)
                    # Salva dentro da pasta images/ do nosso novo zip
                    out_zip.writestr(f"images/{filename}", image_data)
                    
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
    if len(split_pre) < 2: return None, [], "Erro: Sem begin{document}"
    
    preambulo = split_pre[0] + r'\begin{document}'
    corpo = split_pre[1].split(r'\end{document}')[0]
    rodape = r'\end{document}'

    pattern = r'(\\(?:sub)?section\*\{.*?\}|%\s*INICIO BLOCO|%\s*FIM BLOCO)'
    tokens = re.split(pattern, corpo, flags=re.IGNORECASE)
    
    disciplinas = []
    disc_atual = DisciplinaObj("Geral")
    disciplinas.append(disc_atual)
    
    bloco_atual = None
    questao_atual = None
    
    texto_buffer = tokens[0] 
    
    for i in range(1, len(tokens), 2):
        tag = tokens[i].strip()
        conteudo = tokens[i+1] 
        
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

    for disc in disciplinas:
        for item in disc.itens:
            questoes_para_processar = item.questoes if isinstance(item, BlocoObj) else [item]
                
            for q in questoes_para_processar:
                enums = list(re.finditer(r'\\begin\{enumerate\}\s*(?:\[.*?\])?(.*?)\\end\{enumerate\}', q.corpo, re.DOTALL))
                if enums:
                    ultimo_enum = enums[-1]
                    itens_texto = ultimo_enum.group(1)
                    itens_raw = re.split(r'\\item\s*', itens_texto)
                    
                    alternativas_limpas = []
                    idx_correto = -1
                    
                    for idx, it in enumerate([i for i in itens_raw if i.strip()]):
                        it_str = it.strip()
                        match_gabarito = re.search(r'%\s*(CORRETO|CORRETA|CERTA)\b', it_str, re.IGNORECASE)
                        if match_gabarito:
                            idx_correto = idx
                            it_str = it_str.replace(match_gabarito.group(0), '').strip()
                        
                        alternativas_limpas.append(it_str)
                    
                    q.alternativas = alternativas_limpas
                    q.gabarito_orig = idx_correto
                    q.corpo = q.corpo[:ultimo_enum.start()] + "[[ALTS]]" + q.corpo[ultimo_enum.end():]

    disciplinas = [d for d in disciplinas if d.itens]
    return preambulo, disciplinas, rodape

def gerar_latex_embaralhado(preambulo, disciplinas, rodape, seed, sufixo="B"):
    random.seed(seed)
    novo_latex = preambulo + "\n"
    gabarito_final = []
    
    contador_global = 1
    letras = ['(a)', '(b)', '(c)', '(d)', '(e)']

    for disc in disciplinas:
        if disc.nome != "Geral":
            novo_latex += f"\n\\section*{{DISCIPLINA: {disc.nome}}}\n"
        
        itens_shuffled = disc.itens.copy()
        random.shuffle(itens_shuffled)
        
        for item in itens_shuffled:
            if isinstance(item, BlocoObj):
                novo_latex += f"\n{item.texto_apoio}\n"
                questoes_do_bloco = item.questoes
            else:
                questoes_do_bloco = [item]
            
            for q in questoes_do_bloco:
                novo_latex += f"\\subsection*{{Questão {contador_global}}}\n"
                
                indices = list(range(len(q.alternativas)))
                random.shuffle(indices)
                
                bloco_alts = "\\begin{enumerate}[(a)]\n"
                nova_resp_correta = "?"
                idx_correto_original = q.gabarito_orig
                
                for novo_i, original_i in enumerate(indices):
                    txt = q.alternativas[original_i]
                    bloco_alts += f"\\item {txt}\n"
                    
                    if original_i == idx_correto_original:
                        if novo_i < len(letras): 
                            nova_resp_correta = letras[novo_i].replace('(','').replace(')','').upper()
                
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
                    "Versão": f"Prova {sufixo}"
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
                    use_container_width=True
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
        2. Cole o código completo dessa Prova A abaixo e clique em Gerar.
        3. Baixe o ficheiro `.zip`, extraia, e suba os ficheiros `main_B.tex` e `main_C.tex` para a mesma pasta da Prova A no Overleaf.
        4. Recompile e pronto!
        """)

    latex_input = st.text_area("Cole o Código LaTeX da Prova A Original aqui:", height=300)

    col_seed, col_empty = st.columns([1, 3])
    with col_seed:
        seed_val = st.number_input("Semente Inicial (Seed)", value=42)

    if st.button("🎲 Gerar Provas B e C (.zip)", type="primary"):
        if not latex_input.strip():
            st.warning("⚠️ Por favor, cole o código LaTeX antes de gerar.")
        else:
            pre, disc_objs, rod = parse_latex_para_objetos(latex_input)
            
            if disc_objs:
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
                    use_container_width=True
                )
                
                st.caption("🔍 Pré-visualização do Gabarito B:")
                st.dataframe(df_B, hide_index=True)
            else:
                st.error("❌ Não foi possível ler a estrutura da prova. Verifique se copiou o código inteiro (incluindo \\begin{document}).")
