from pdf_reader import extrair_texto
import streamlit as st

# Configuração da página
st.set_page_config(
    page_title="Acadêmico IA",
    page_icon="📚",
    layout="centered"
)

# Título
st.title("📚 Acadêmico IA")

st.write(
    "Envie seu documento acadêmico e receba "
    "um resumo organizado com auxílio da Inteligência Artificial."
)

# Upload do documento
arquivo = st.file_uploader(
    "Envie seu documento em PDF",
    type=["pdf"]
)

# Botão para gerar resumo
if st.button("Gerar resumo"):

    if arquivo is not None:
        st.success("Documento recebido com sucesso!")

        st.write("Seu resumo será gerado aqui.")

    else:
        st.warning("Por favor, envie um arquivo PDF.")
