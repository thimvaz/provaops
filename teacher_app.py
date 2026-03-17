import streamlit as st
import pandas as pd
import re
import random
import zipfile
from io import BytesIO

st.set_page_config(page_title="ProvaOps - Sistema de Provas", layout="wide", page_icon="📝")

# ==========================================
# FUNÇÕES DO NÚCLEO (BACKEND)
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

    # Extração de alternativas mais robusta contra espaços e formatos
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
                        
                        # Nova busca robusta por variações do marcador de gabarito
                        match_gabarito = re.search(r'%\s*(CORRETO|CORRETA|CERTA)\b', it_str, re.IGNORECASE)
                        if match_gabarito:
                            idx_correto = idx
                            # Limpa o comentário da versão gerada
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
                novo_latex += f"\\section*{{Questão {contador_global}}}\n"
                
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

st.title("🚀 Escola Analítica: ProvaOps - Embaralhador")

with st.expander("📖 INSTRUÇÕES PARA O EDITOR (Clique para expandir)", expanded=True):
    st.markdown("""
    ### 1. Preparando o arquivo no Overleaf (Prova A)
    Para que o embaralhador funcione perfeitamente, seu código LaTeX precisa ter 3 marcações:
    * **Divisão de Disciplinas:** Use o comando `\\section*{DISCIPLINA: Nome da Matéria}` antes da primeira questão de cada matéria.
    * **Textos de Apoio (Indissociáveis):** Se um texto serve para mais de uma questão, coloque `% INICIO BLOCO` antes do texto e `% FIM BLOCO` após a última questão referente a ele.
    * **Gabarito:** Coloque `%CORRETO` dentro da alternativa certa (logo após o comando `\\item`).
    
    ### 2. O que fazer com o arquivo gerado?
    1. Cole o código da sua Prova A abaixo e clique em Gerar.
    2. Baixe o arquivo `.zip` e extraia os arquivos no seu computador.
    3. Vá no seu projeto do Overleaf e **faça o upload dos arquivos `main_B.tex` e `main_C.tex` para a mesma pasta onde estão suas imagens**.
    4. Selecione o arquivo B ou C no Overleaf e clique em Recompilar para gerar o PDF da nova versão!
    """)

st.divider()

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
            # Gera Versão B
            tex_B, gab_B = gerar_latex_embaralhado(pre, disc_objs, rod, seed_val, "B")
            df_B = pd.DataFrame(gab_B)
            
            # Gera Versão C (usando uma semente diferente)
            tex_C, gab_C = gerar_latex_embaralhado(pre, disc_objs, rod, seed_val + 10, "C")
            df_C = pd.DataFrame(gab_C)
            
            st.success("✅ Provas geradas com sucesso!")
            st.divider()
            
            # Criação do ZIP
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                zip_file.writestr("Prova_B/main_B.tex", tex_B)
                zip_file.writestr("Prova_B/Gabarito_B.csv", df_B.to_csv(index=False))
                zip_file.writestr("Prova_C/main_C.tex", tex_C)
                zip_file.writestr("Prova_C/Gabarito_C.csv", df_C.to_csv(index=False))
                
            zip_buffer.seek(0)
            
            c1, c2 = st.columns([1, 2])
            with c1:
                st.download_button(
                    label="📥 Baixar Pacote Completo (.zip)",
                    data=zip_buffer,
                    file_name=f"Provas_Embaralhadas_Seed{seed_val}.zip",
                    mime="application/zip",
                    use_container_width=True
                )
            
            st.caption("🔍 Pré-visualização do Gabarito B:")
            st.dataframe(df_B, hide_index=True)
        else:
            st.error("❌ Não foi possível ler a estrutura da prova. Verifique se copiou o código inteiro (incluindo \\begin{document}).")
