import streamlit as st
import pandas as pd
import docx
import re
import random
from io import StringIO

st.set_page_config(page_title="ProvaOps - Sistema de Provas", layout="wide", page_icon="📝")

# ==========================================
# FUNÇÕES DO NÚCLEO (BACKEND)
# ==========================================

def clean_text(text):
    return text.strip()

def extrair_numero_questao(titulo):
    """
    Tenta extrair o número de uma string como 'Questão 5' ou 'Física - Questão 05'
    Retorna string '5' ou None.
    """
    match = re.search(r'(\d+)', titulo)
    if match:
        return str(int(match.group(1))) # Converte para int e volta para str para remover zeros à esquerda
    return None

def extrair_gabarito_docx(docx_file):
    """
    Lê o arquivo de gabarito e retorna um dicionário:
    {'Física': {'1': 'A', '2': 'C'}, 'História': {'1': 'D'}}
    """
    doc = docx.Document(docx_file)
    gabarito_map = {}
    disciplina_atual = "Geral"
    
    # Regex para capturar "1 - A", "1. A", "1 A", "1) A"
    regex_resp = re.compile(r'^\s*(\d+)[\s\.\-\)]+([a-eA-E])', re.IGNORECASE)
    
    for para in doc.paragraphs:
        texto = clean_text(para.text)
        estilo = para.style.name
        
        # Detecção de Disciplina (Heading 1 / Título 1)
        if estilo.startswith('Heading 1') or estilo.startswith('Título 1'):
            disciplina_atual = texto
            if disciplina_atual not in gabarito_map:
                gabarito_map[disciplina_atual] = {}
            continue
            
        if not texto: continue
        
        # Detecção da Resposta
        match = regex_resp.match(texto)
        if match:
            num = str(int(match.group(1))) # Normaliza '01' para '1'
            letra = match.group(2).upper()
            
            if disciplina_atual not in gabarito_map:
                gabarito_map[disciplina_atual] = {}
            
            gabarito_map[disciplina_atual][num] = letra
            
    return gabarito_map

def converter_docx_para_latex(docx_file, gabarito_full):
    doc = docx.Document(docx_file)
    latex_output = ""
    
    latex_output += r"""
\documentclass[a4paper,10pt]{exam}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage[brazil]{babel}
\usepackage{graphicx}
\usepackage{enumitem}
\usepackage{geometry}
\geometry{a4paper, left=10mm, right=10mm, top=15mm, bottom=20mm}

\begin{document}
"""
    regex_questao = re.compile(r'^\s*(?:Questão\s+)?(\d+)[\.\)\-\s]+', re.IGNORECASE)
    regex_alternativa = re.compile(r'^\s*([a-eA-E])[\.\)\-\s]+')
    
    dentro_enumerate = False
    disciplina_atual = "Geral"
    contador_imagens = 1
    
    for para in doc.paragraphs:
        texto = clean_text(para.text)
        estilo = para.style.name
        
        if estilo.startswith('Heading 1') or estilo.startswith('Título 1'):
            if dentro_enumerate:
                latex_output += "\\end{enumerate}\n\n"
                dentro_enumerate = False
            disciplina_atual = texto
            latex_output += f"\n% ==========================================\n"
            latex_output += f"\\section*{{DISCIPLINA: {disciplina_atual}}}\n" 
            latex_output += f"% ==========================================\n"
            continue

        if 'graphic' in para._element.xml:
            nome_img = f"images/image{contador_imagens}.png"
            latex_output += "\\begin{center}\n"
            latex_output += f"    \\includegraphics[width=0.8\\linewidth]{{{nome_img}}}\n"
            latex_output += "\\end{center}\n"
            contador_imagens += 1

        if not texto: continue
            
        match_q = regex_questao.match(texto)
        match_alt = regex_alternativa.match(texto)
        
        if match_q:
            if dentro_enumerate:
                latex_output += "\\end{enumerate}\n\n"
                dentro_enumerate = False
            
            num_q = str(int(match_q.group(1)))
            resto_texto = texto[match_q.end():].strip()
            
            resp = "?"
            if disciplina_atual in gabarito_full:
                resp = gabarito_full[disciplina_atual].get(num_q, "?")
            
            latex_output += f"\\subsection*{{Questão {num_q}}}\n"
            latex_output += f"% Gabarito Original: {resp}\n"
            latex_output += f"{resto_texto}\n\n"
            
        elif match_alt:
            if not dentro_enumerate:
                latex_output += "\\begin{enumerate}[(a)]\n"
                dentro_enumerate = True
            resto_texto = texto[match_alt.end():].strip()
            latex_output += f"\\item {resto_texto}\n"
            
        else:
            if dentro_enumerate: 
                latex_output += "\\end{enumerate}\n\n"
                dentro_enumerate = False
            latex_output += f"{texto}\n\n"

    if dentro_enumerate:
        latex_output += "\\end{enumerate}\n"

    latex_output += "\\end{document}"
    return latex_output

# --- CLASSES PARA O EMBARALHADOR ---
class QuestaoObj:
    def __init__(self, titulo, corpo, alternativas, gabarito_orig, disciplina):
        self.titulo = titulo
        self.corpo = corpo
        self.alternativas = alternativas
        self.gabarito_orig = gabarito_orig
        self.disciplina = disciplina

class DisciplinaObj:
    def __init__(self, nome):
        self.nome = nome
        self.questoes = []

def parse_latex_para_objetos(latex_content, gabarito_externo=None):
    """
    Lê o LaTeX e cria objetos.
    Se gabarito_externo for fornecido (dict), usa ele quando não achar o comentário interno.
    """
    split_pre = latex_content.split(r'\begin{document}')
    if len(split_pre) < 2: return None, [], "Erro: Sem begin{document}"
    
    preambulo = split_pre[0] + r'\begin{document}'
    corpo = split_pre[1].split(r'\end{document}')[0]
    rodape = r'\end{document}'

    secoes_raw = re.split(r'(\\(?:sub)?section\*\{.*?\})', corpo)
    
    disciplinas = []
    disc_atual = None
    questao_atual = None
    
    iterator = iter(secoes_raw)
    try:
        next(iterator) 
    except StopIteration:
        pass

    while True:
        try:
            tag = next(iterator)
            conteudo = next(iterator)
        except StopIteration:
            break
            
        titulo_limpo = tag.replace(r'\section*{', '').replace(r'\subsection*{', '').replace('}', '').strip()
        
        # --- LÓGICA DE DETECÇÃO HÍBRIDA ---
        
        # 1. Disciplina Explícita
        if "DISCIPLINA:" in titulo_limpo:
            nome_disc = titulo_limpo.replace("DISCIPLINA:", "").strip()
            disc_atual = DisciplinaObj(nome_disc)
            disciplinas.append(disc_atual)
            questao_atual = None 
            continue

        # 2. Matéria - Questão X
        elif " - " in titulo_limpo and "Questão" in titulo_limpo:
            partes = titulo_limpo.split(" - ")
            nome_disc = partes[0].strip()
            
            if disc_atual is None or disc_atual.nome != nome_disc:
                disc_atual = DisciplinaObj(nome_disc)
                disciplinas.append(disc_atual)
            
            questao_atual = QuestaoObj(titulo_limpo, "", [], "?", disc_atual.nome)
            disc_atual.questoes.append(questao_atual)

        # 3. Apenas Questão
        elif "Questão" in titulo_limpo:
            if disc_atual is None:
                disc_atual = DisciplinaObj("Geral")
                disciplinas.append(disc_atual)
            
            questao_atual = QuestaoObj(titulo_limpo, "", [], "?", disc_atual.nome)
            disc_atual.questoes.append(questao_atual)
            
        # 4. Títulos Avulsos que parecem disciplinas
        elif any(mat in titulo_limpo for mat in ["História", "Física", "Matemática", "Geografia", "Biologia", "Química", "Português", "Inglês"]):
             disc_atual = DisciplinaObj(titulo_limpo)
             disciplinas.append(disc_atual)
             questao_atual = None
             continue
        else:
            if questao_atual:
                questao_atual.corpo += f"\n{tag}\n{conteudo}"
            continue

        # --- EXTRAÇÃO DE CONTEÚDO ---
        if questao_atual:
            # A. Tenta achar gabarito embutido
            match_gab = re.search(r'% Gabarito Original:\s*([A-E\?])', conteudo)
            if match_gab:
                questao_atual.gabarito_orig = match_gab.group(1)
            
            # B. Se não achou e tem gabarito externo, tenta cruzar
            elif gabarito_externo:
                num_q = extrair_numero_questao(titulo_limpo)
                if num_q:
                    # Tenta achar na disciplina atual ou na Geral
                    resp = "?"
                    if disc_atual.nome in gabarito_externo:
                        resp = gabarito_externo[disc_atual.nome].get(num_q, "?")
                    elif "Geral" in gabarito_externo:
                         resp = gabarito_externo["Geral"].get(num_q, "?")
                    
                    if resp != "?":
                        questao_atual.gabarito_orig = resp

            # Extração de Alternativas
            match_enum = re.search(r'\\begin\{enumerate\}.*?\]?(.*)\\end\{enumerate\}', conteudo, re.DOTALL)
            
            if match_enum:
                itens_texto = match_enum.group(1)
                itens = re.split(r'\\item\s?', itens_texto)
                questao_atual.alternativas = [it.strip() for it in itens if it.strip()]
                
                texto_limpo = conteudo.replace(match_enum.group(0), "[[ALTS]]")
                questao_atual.corpo = texto_limpo
            else:
                questao_atual.corpo = conteudo

    disciplinas = [d for d in disciplinas if d.questoes]
    return preambulo, disciplinas, rodape

def gerar_latex_embaralhado(preambulo, disciplinas, rodape, seed):
    random.seed(seed)
    novo_latex = preambulo + "\n"
    gabarito_final = []
    
    contador_global = 1
    letras = ['(a)', '(b)', '(c)', '(d)', '(e)']
    map_letra_idx = {'A':0, 'B':1, 'C':2, 'D':3, 'E':4}

    for disc in disciplinas:
        novo_latex += f"\n\\section*{{{disc.nome}}}\n"
        
        questoes_shuffled = disc.questoes.copy()
        random.shuffle(questoes_shuffled)
        
        for q in questoes_shuffled:
            novo_latex += f"\\subsection*{{Questão {contador_global}}}\n"
            
            indices = list(range(len(q.alternativas)))
            random.shuffle(indices)
            
            bloco_alts = "\\begin{enumerate}[(a)]\n"
            nova_resp_correta = "?"
            
            idx_correto_original = map_letra_idx.get(q.gabarito_orig, -1)
            
            for novo_i, original_i in enumerate(indices):
                txt = q.alternativas[original_i]
                bloco_alts += f"\\item {txt}\n"
                
                if original_i == idx_correto_original:
                    if novo_i < 5: nova_resp_correta = letras[novo_i].replace('(','').replace(')','').upper()
            
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
                "Origem": q.titulo
            })
            
            contador_global += 1
            
    novo_latex += rodape
    return novo_latex, gabarito_final

# ==========================================
# INTERFACE (FRONTEND)
# ==========================================

st.title("🚀 Escola Analítica: ProvaOps")

tab_acelerador, tab_embaralhador = st.tabs(["1. Acelerador (Docx -> LaTeX)", "2. Embaralhador (Geração de Provas)"])

# --- ABA 1: ACELERADOR ---
with tab_acelerador:
    st.header("Conversor Inteligente")
    st.info("Passo 1: Suba o arquivo com as questões (texto + imagens) e o arquivo apenas com o gabarito.")
    
    col1, col2 = st.columns(2)
    with col1:
        file_prova = st.file_uploader("📂 Arquivo da PROVA (.docx)", type=['docx'])
    with col2:
        file_gabarito = st.file_uploader("✅ Arquivo de GABARITO (.docx)", type=['docx'])
        
    if file_prova and file_gabarito:
        if st.button("🚀 Processar e Gerar LaTeX"):
            try:
                gabarito_map = extrair_gabarito_docx(file_gabarito)
                st.toast("Gabarito lido com sucesso!", icon="✅")
                
                latex_gerado = converter_docx_para_latex(file_prova, gabarito_map)
                
                st.success("Conversão Concluída!")
                st.markdown("Copie o código abaixo e vá para a aba **Embaralhador**, ou salve para editar no Overleaf.")
                st.text_area("Código LaTeX Base", value=latex_gerado, height=400, key="latex_output")
                
                st.session_state['latex_cache'] = latex_gerado
                
            except Exception as e:
                st.error(f"Erro ao processar: {e}")

# --- ABA 2: EMBARALHADOR ---
with tab_embaralhador:
    st.header("Gerador de Versões")
    st.markdown("Se você usou o Acelerador, o código já está abaixo. Se tem um arquivo LaTeX bruto, cole-o e suba o gabarito.")
    
    col_input, col_gab_extra = st.columns([2, 1])
    
    with col_input:
        latex_input = st.text_area("Código LaTeX:", 
                                   value=st.session_state.get('latex_cache', ''), 
                                   height=300)
    
    with col_gab_extra:
        st.info("Arquivo Bruto? Suba o Gabarito aqui:")
        file_gabarito_extra = st.file_uploader("Gabarito (.docx) [Opcional]", type=['docx'], key="gab_extra")
    
    if latex_input:
        col_seed, col_act = st.columns([1, 2])
        with col_seed:
            seed_val = st.number_input("Semente (Seed)", value=42)
        
        if st.button("🎲 Gerar Prova Embaralhada"):
            # Lógica para ler gabarito externo se fornecido
            mapa_gab_externo = None
            if file_gabarito_extra:
                try:
                    mapa_gab_externo = extrair_gabarito_docx(file_gabarito_extra)
                    st.toast("Gabarito externo carregado!", icon="✅")
                except:
                    st.error("Erro ao ler gabarito externo.")

            # Parser com suporte a gabarito externo
            pre, disc_objs, rod = parse_latex_para_objetos(latex_input, mapa_gab_externo)
            
            if disc_objs:
                # Gerador
                tex_final, df_gab = gerar_latex_embaralhado(pre, disc_objs, rod, seed_val)
                
                st.divider()
                c1, c2 = st.columns(2)
                
                with c1:
                    st.subheader("Arquivo LaTeX (.tex)")
                    st.download_button("📥 Baixar Prova.tex", tex_final, f"prova_seed_{seed_val}.tex")
                    
                with c2:
                    st.subheader("Gabarito da Versão")
                    df = pd.DataFrame(df_gab)
                    st.dataframe(df, hide_index=True)
                    st.download_button("📥 Baixar Gabarito.csv", df.to_csv(index=False), f"gabarito_seed_{seed_val}.csv")
            else:
                st.error("Não foi possível ler as disciplinas. Verifique os marcadores do LaTeX.")
