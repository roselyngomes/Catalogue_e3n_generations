########################################
#Description      :   PROGRAMME DE TEST : Développement en local de la page web pour sélection les variables 
#                     à partir du fichier dicotionnaire des variables.
#DATE OF CREATION :   06/08/2026							                                                                            
#DATE OF UPDATE	  :   14/08/2026								                                                                              
# AUTHOR		  :   Roselyn Gomes					                                                                                 
################################################################################################################

# Importer LES PACKAGES NÉCESSAIRES

import pandas as pd
import streamlit as st
import getpass
import datetime
import io
import base64
import os

# Configurer style

def load_css():

    with open("Documents/APP/style.css") as f:

        st.markdown(
            f"<style>{f.read()}</style>",
            unsafe_allow_html=True
        )

# Configurer la page en mode large
st.set_page_config(page_title='E3N Générations', layout='wide')

load_css()

col1, col2 = st.columns([1, 6])

with col1:
    st.markdown("<div style='margin-top:30px'></div>",
                unsafe_allow_html=True)
    st.image("Documents/APP/images/e3n-generations-logo.png", width=150)
with col2:
    st.title("Catalogue de données E3N-Générations")
    
    st.write("""Le catalogue documentaire des variables et questionnaires généraux de la cohorte E3N-Générations.""")

@st.cache_data
def load_data():
    # Charger le fichier Excel
    file_path = 'Documents/APP/20250916_dicovar_reflexion_e3n.xlsx'
    df = pd.read_excel(file_path, sheet_name='Dicovar')
    df.reset_index(inplace=True)
    df.rename(columns={"index": "ID"}, inplace=True)
    return df

df = load_data()

@st.cache_data
def load_questionnaires():
    try:
        return pd.read_excel('Documents/APP/20250916_dicovar_reflexion_e3n.xlsx', sheet_name='questionnaire')
    except:
        return pd.DataFrame()
    
qdf = load_questionnaires()


def afficher_pdf(pdf_path):
    if not os.path.exists(pdf_path):
        st.warning(f'PDF introuvable : {pdf_path}')
        return
    with open(pdf_path,'rb') as f:
        b64 = base64.b64encode(f.read()).decode()
    html = f'<iframe src="data:application/pdf;base64,{b64}" width="100%" height="800"></iframe>'
    st.markdown(html, unsafe_allow_html=True)

if 'ID' not in df.columns:
    df = df.reset_index().rename(columns={'index':'ID'})

if 'selected_ids' not in st.session_state:
    st.session_state.selected_ids = set()

accueil, questionnaires, documentation,variables = st.tabs([
    '🏠 E3N-Générations',
    '📄 Questionnaires',
    '📂 Documentation',
    '📚 Variables'
])


with accueil:
    st.write("""L’étude E3N-Générations s’appuie sur un ensemble de familles sur trois générations, une cohorte familiale qui comptera à terme 170 000 participants.
            L'étude familiale prolonge l’étude E3N (Etude Epidémiologique auprès de femmes de l’Education Nationale) qui suit activement environ 100 000 femmes depuis 1990, en invitant leurs enfants, les pères de ces enfants et leurs petits-enfants à participer à leur tour.
            E3N-Générations est l'une des deux seules études épidémiologiques au monde de cette ampleur rassemblant des familles sur trois générations.
            Les membres d’une même famille ont en commun des gènes, des habitudes et des lieux de vie. Cette vaste communauté de familles est un outil de recherche puissant pour démêler ce qui, dans notre santé, relève de la génétique, du mode de vie ou de l’environnement.""")

    st.image(
            "Documents/APP/images/Schema_E3N-Generations_20250613.png",
            width=500
        )
    st.header('Les données épidémiologiques recueillies')
    st.write("""Pour les besoins de cette étude prospective de cohorte familiale, des données très détaillées sont collectées sur les caractéristiques personnelles, le mode de vie et la santé des participants.""")

    st.info("""Calendrier de suivi des volontaires de la cohorte E3N-Générations""")

    st.image(
            "Documents/APP/images/Calendrier_E3N_Generations_202606.png",
            use_container_width=True
        )
 
    st.markdown('**Liens utiles**')
    st.markdown('- https://www.e3n-generations.fr/')

# Initialiser la sélection dans session_state
if "selected_ids" not in st.session_state:
    st.session_state.selected_ids = set()

# -------------------
# Dans l'onglet variables
# -------------------

with variables:

    # Restreindre la liste des questionnaires en fonction de la generation choisie

    st.subheader("Filtrer les variables")

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        selected_generation = st.selectbox(
            "Par génération",
            ["Toutes"] + sorted(df["generation"].dropna().unique().tolist())
        )
        if selected_generation == "Toutes":
                questionnaires_disponibles = df["quest"].dropna().unique().tolist()
        else:
                questionnaires_disponibles = df.loc[df["generation"] == selected_generation, "quest"].dropna().unique().tolist()

    with col2:
        selected_questionnaire = st.selectbox(
            "Par questionnaire",
            ["Tous"] + sorted(df["quest"].dropna().unique().tolist())
        )

    with col3:
        selected_theme = st.selectbox(
            "Par Thème :",
            ["Tous"] + sorted(df["theme"].dropna().unique().tolist())
    )
        
    with col4:
        selected_sstheme = st.selectbox(
            "Par sous-thème :",
            ["Tous"] + sorted(df["sstheme"].dropna().unique().tolist())
    )
        
    with col5:
        selected_etat = st.selectbox(
             "Par état d'utilisation :",
             ["Tous"] + sorted(df["var_etat"].dropna().unique().tolist())
    )

   
    # -------------------
    # Application des filtres
    # -------------------
    filtered_df = df.copy()

    # Ne pas afficher les variables masquées
    filtered_df = filtered_df[filtered_df["var_affiche"] != "non"]

    if selected_generation != "Toutes":
        filtered_df = filtered_df[filtered_df["generation"] == selected_generation]
    if selected_questionnaire != "Tous":
        filtered_df = filtered_df[filtered_df["quest"] == selected_questionnaire]
    if selected_theme != "Tous":
        filtered_df = filtered_df[filtered_df["theme"] == selected_theme]
    if selected_sstheme != "Tous":
        filtered_df = filtered_df[filtered_df["sstheme"] == selected_sstheme]
    if selected_etat != "Tous":
        filtered_df = filtered_df[filtered_df["var_etat"] == selected_etat]

    # -------------------
    # Sélection interactive
    # -------------------
    filtered_df["Sélectionné"] = filtered_df["ID"].apply(lambda x: x in st.session_state.selected_ids)

    st.subheader("Liste des Variables")
    edited_df = st.data_editor(
        filtered_df[["ID","quest", "generation", "theme", "sstheme", "var_etat","var_brut","var_nett", "var_genere","desc_trans","desc_genere","Sélectionné"]],
        column_config={"Sélectionné": st.column_config.CheckboxColumn()},
        use_container_width=True,
        key="data_editor"
    )

    # Mettre à jour la sélection
    for idx, row in edited_df.iterrows():
        id_ = row["ID"]
        if row["Sélectionné"]:
            st.session_state.selected_ids.add(id_)
        else:
            st.session_state.selected_ids.discard(id_)

    # -------------------
    # Variables sélectionnées
    # -------------------


    st.subheader("Variables Sélectionnées")
    selected_df = df[df["ID"].isin(st.session_state.selected_ids)]

    if not selected_df.empty:
        # Ajout d'une colonne de désélection
        selected_df["Désélectionner"] = selected_df["ID"].apply(lambda x: False)

        edited_selected = st.data_editor(
            selected_df[["ID", "quest", "generation", "theme", "var_etat", "sstheme","var_brut","var_nett", "var_genere","desc_trans","var_trans", "Désélectionner"]],
            column_config={"Désélectionner": st.column_config.CheckboxColumn()},
            use_container_width=True,
            key="selected_editor"
        )

        # Mettre à jour la sélection : si une case est cochée, on enlève l'ID
        for idx, row in edited_selected.iterrows():
            if row["Désélectionner"]:
                st.session_state.selected_ids.discard(row["ID"])

        st.write(f"**Nombre de variables sélectionnées :** {len(st.session_state.selected_ids)}")
    else:
        st.write("Aucune variable sélectionnée.")

    # -------------------
    st.subheader("Téléchargement (Excel/CSV)")

    # Demande du nom de projet #  
    project_name = st.text_input("Merci d'indiquer un acronyme du projet_votre nom :", value="")
    # -------------------
    today = datetime.date.today().strftime("%Y%m%d")

    # -------------------
    # Export en téléchargement direct
    # -------------------
    buffer = io.BytesIO()
    selected_df.to_excel(buffer, index=False)
    buffer.seek(0)

    csv = selected_df.to_csv(
        index=False,
        sep=";"
        ).encode("utf-8")

if st.button("Préparer le téléchargement"):
    st.warning(
    "⚠️ Le nom du projet est obligatoire."
)
else:
    st.download_button(
        label="Télécharger en Excel",
        data=buffer,
        file_name=f"{project_name}_{today}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
if not project_name.strip():    
    st.download_button(
        label="Télécharger en CSV",
        data=csv,
        file_name=f"{project_name}_{today}.csv",
        mime="text/csv"
    )
    st.error(
    "⚠️ Veuillez renseigner un acronyme du projet_votre nom avant le téléchargement."
    )
else:
    st.download_button(
        label="Télécharger en CSV",
        data=csv,
        file_name=f"{project_name}_{today}.csv",
        mime="text/csv"
    )
# -------------------
# Dans l'onglet questionnaires
# -------------------

with questionnaires:

    st.header("Questionnaires")

    # ====================================
    # Filtre génération
    # ====================================
    generation_labels = {
        "G1F": "G1-Femmes (G1F)",
        "G1H": "G1-Hommes (G1H)"
    }
    
    generations = qdf["generation"].dropna().unique()
    generation_select = st.radio(
                "Par génération",
                generations,
                horizontal=True,
                format_func=lambda x: generation_labels.get(x, x)
                )

    qdf_filtre = qdf[
        qdf["generation"] == generation_select
    ]

    # ====================================
    # Affichage spécifique G1F
    # ====================================

    if generation_select == "G1F":

        st.subheader(
            "Calendrier des questionnaires Femmes G1"
        )


        st.info("""
        Cette frise présente l'ensemble des questionnaires papier adressés aux femmes de la génération G1 depuis leur inclusion dans la cohorte E3N.
        """)
        
        st.image(
            "Documents/APP/images/Calendrier_E3N_G1_Femmes_202606.png",
            use_container_width=True
        )

    # ====================================
    # Affichage spécifique G1H
    # ====================================

    if generation_select == "G1H":

        st.subheader(
            "Calendrier des questionnaires Hommes G1"
        )


        st.info("""
        Cette frise présente l'ensemble des questionnaires papier adressés aux pères des enfants des femmes E3N, 
        qui forment avec elles la première génération de la cohorte E3N-Générations, 
        """)
        
        st.image(
            "Documents/APP/images/Calendrier_E3N_G1_Hommes_202606_0.png",
            use_container_width=True
        )

    # ====================================
    # Sélection questionnaire
    # ====================================

    q = qdf_filtre["quest"].dropna().unique()
    q_select = st.radio(
                "Questionnaire",
                q,
                horizontal=True
                )
    
    ligne = qdf_filtre[
        qdf_filtre["quest"] == q_select
    ].iloc[0]



    # ====================================
    # Informations questionnaire
    # ====================================

    col1, col2 = st.columns([1,2])

    with col1:

        st.subheader(ligne["titre"])
        st.write(ligne["description"])

    with col2:

        if pd.notna(ligne["url_pdf"]):

            pdf_url = (
            ligne["url_pdf"]    
        + ligne["pdf_file"])    
    st.link_button("📄 Ouvrir le questionnaire", pdf_url)

# -------------------
# Dans l'onglet documentation
# -------------------

with documentation:
    st.subheader('Documentation')
    st.markdown('Déposer ici les guides utilisateurs, dictionnaires et publications.')

