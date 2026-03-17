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
                bloco_
