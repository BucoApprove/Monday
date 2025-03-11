import streamlit as st
import requests
import json
import pandas as pd
from typing import Dict, List, Optional, Union, Any
import re
from datetime import datetime, timedelta
import numpy as np
import os

st.set_page_config(page_title="Monday.com Dashboard", layout="wide")

# Título da aplicação
st.title("Monday.com Dashboard")

# Configuração Monday.com
API_TOKEN = st.sidebar.text_input("API Token do Monday.com", 
                                  value="eyJhbGciOiJIUzI1NiJ9.eyJ0aWQiOjQ2NDIwMDY2NywiYWFpIjoxMSwidWlkIjoxODEzOTYyOCwiaWFkIjoiMjAyNS0wMS0yOFQxMTozMDozNS43ODRaIiwicGVyIjoibWU6d3JpdGUiLCJhY3RpZCI6Nzk0NDk2MywicmduIjoidXNlMSJ9.IWYJd4x3UTFFPAec925cwbriVjusgX4xTzxzFDj_w24",
                                  type="password")
API_URL = "https://api.monday.com/v2"

# Cache para funções que usamos repetidamente
@st.cache_data(ttl=3600)
def fetch_all_boards(api_token):
    all_boards = []
    page = 1
    limit = 100  # Ajuste conforme o limite do seu plano
    headers = {"Authorization": api_token}

    while True:
        query = f"""
        query {{
          boards (state: all, limit: {limit}, page: {page}) {{
            id
            name
            description
            owner {{
              id
              name
            }}
            permissions
            state
            board_kind
            columns {{
              id
              title
              type
              settings_str
            }}
            groups {{
              id
              title
            }}
            items_count
            workspace {{
              id
              name
            }}
          }}
        }}
        """
        response = requests.post(API_URL, json={"query": query}, headers=headers)
        
        if response.status_code != 200:
            st.error(f"Erro ao buscar quadros: {response.status_code} - {response.text}")
            return []
            
        data = response.json()
        if not data or "data" not in data or "boards" not in data["data"]:
            break

        boards = data["data"]["boards"]
        if not boards:
            break

        all_boards.extend(boards)
        page += 1

    return all_boards

@st.cache_data(ttl=3600)
def get_user_map(api_token):
    headers = {"Authorization": api_token}
    query = """
    query {
      users {
        id
        name
      }
    }
    """
    response = requests.post(API_URL, json={"query": query}, headers=headers)
    
    if response.status_code != 200:
        st.error(f"Erro ao buscar usuários: {response.status_code} - {response.text}")
        return {}
        
    data = response.json()
    if data and "data" in data and "users" in data["data"]:
        return {str(user["id"]): user["name"] for user in data["data"]["users"]}
    return {}

@st.cache_data(ttl=3600)
def extract_status_maps(boards):
    status_labels_map = {}
    
    for board in boards:
        for column in board.get("columns", []):
            if column["type"] == "status" and column.get("settings_str"):
                try:
                    settings = json.loads(column["settings_str"])
                    if "labels" in settings:
                        # Criar mapeamento de índice para rótulo
                        column_map = {}
                        for index, label in enumerate(settings["labels"]):
                            if isinstance(label, dict) and "name" in label:
                                column_map[str(index)] = label["name"]
                            elif isinstance(label, str):
                                column_map[str(index)] = label
                        
                        if column_map:
                            status_labels_map[column["id"]] = column_map
                except (json.JSONDecodeError, Exception) as e:
                    st.warning(f"Erro ao extrair configurações de status para coluna {column['id']}: {str(e)}")
    
    return status_labels_map

# Função para obter todos os status possíveis
def get_all_status_values(boards, status_labels_map):
    all_status = set()
    
    # Adicionar status conhecidos do mapeamento
    for column_id, status_map in status_labels_map.items():
        for status_value in status_map.values():
            all_status.add(status_value)
    
    # Adicionar status padrão que podem não estar no mapeamento
    default_status = ["Em Andamento", "Feito", "Parado", "Pendente", "Aguardando", "Concluído", "Em Progresso"]
    for status in default_status:
        all_status.add(status)
    
    return sorted(list(all_status))

# Função para fazer a chamada à API do Monday
def make_request(query, api_token):
    headers = {"Authorization": api_token}
    response = requests.post(API_URL, json={"query": query}, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        st.error(f"Erro na API: {response.status_code} - {response.text}")
        return None

# Função para identificar colunas específicas com base em tipo e título
def identify_column(columns, column_type, possible_titles):
    for column in columns:
        if column["type"] == column_type and any(title.lower() in column["title"].lower() for title in possible_titles):
            return column
    for column in columns:
        if column["type"] == column_type:
            return column
    return None

# Função melhorada para extrair qualquer valor de coluna com tratamento específico para cada tipo
# Função ajustada para extrair valores de coluna
def extract_column_value(column_id, column_type, column_values, status_labels_map):
    if not column_id or column_id not in column_values:
        return f"No {column_type}"
    
    value = column_values[column_id].get("value")
    text = column_values[column_id].get("text", "")
    
    # Se não houver valor, usar texto se disponível
    if not value:
        return text if text else f"No {column_type}"
    
    # Tratamento específico para cada tipo de coluna
    if column_type == "status":
        # Mapeamento fixo de status
        status_mapping = {
            "0": "Em Andamento",
            "1": "Feito",
            "2": "Parado"
        }
        
        try:
            parsed_value = json.loads(value)
            
            # Caso 1: Formato padrão do Monday com index
            if isinstance(parsed_value, dict) and "index" in parsed_value:
                index = str(parsed_value.get("index"))
                
                # Verificar se o índice está no mapeamento fixo (prioridade)
                if index in status_mapping:
                    return status_mapping[index]
                
                # Caso contrário, verificar se temos um mapeamento no status_labels_map
                if column_id in status_labels_map and index in status_labels_map[column_id]:
                    return status_labels_map[column_id][index]
                
                # Se não houver mapeamento, usar o texto se disponível
                return text if text else f"Status {index}"
            
            # Caso 2: Formato com label explícito
            elif isinstance(parsed_value, dict) and "label" in parsed_value:
                if isinstance(parsed_value["label"], dict):
                    return parsed_value["label"].get("text", text if text else f"No {column_type}")
                return str(parsed_value["label"])
            
            # Caso 3: Outros formatos (como múltiplas alterações)
            elif re.search(r'\{.*?\}\{.*?\}', value):
                # Extrair o último status com changed_at
                matches = re.findall(r'\{.*?"index":\s*(\d+).*?"changed_at":\s*"([^"]+)".*?\}', value)
                if matches:
                    # Ordenar por data e pegar o mais recente
                    matches.sort(key=lambda x: x[1], reverse=True)
                    latest_index = matches[0][0]
                    
                    # Verificar se o índice está no mapeamento fixo (prioridade)
                    if latest_index in status_mapping:
                        return status_mapping[latest_index]
                    
                    # Caso contrário, verificar se temos um mapeamento no status_labels_map
                    if column_id in status_labels_map and latest_index in status_labels_map[column_id]:
                        return status_labels_map[column_id][latest_index]
                    
                    return text if text else f"Status {latest_index}"
            
            # Caso padrão: usar o texto ou valor bruto
            return text if text else str(parsed_value)
                
        except json.JSONDecodeError:
            # Se o valor não for JSON, usar o texto ou tratar como valor direto
            if text and text != "":
                return text
            return f"No {column_type}"
    
    # (O restante da função permanece igual)
    elif column_type == "date":
        try:
            parsed_value = json.loads(value)
            if isinstance(parsed_value, dict) and "date" in parsed_value:
                return parsed_value["date"]
            return text if text else str(parsed_value)
        except json.JSONDecodeError:
            return text if text else f"No {column_type}"
    
    elif column_type == "person":
        try:
            parsed_value = json.loads(value)
            if isinstance(parsed_value, dict) and "personsAndTeams" in parsed_value:
                persons = []
                for person in parsed_value["personsAndTeams"]:
                    if person.get("kind") == "person":
                        persons.append(str(person.get("id", "")))
                return ",".join(persons)
            return text if text else f"No {column_type}"
        except json.JSONDecodeError:
            return text if text else f"No {column_type}"
    
    else:
        try:
            parsed_value = json.loads(value)
            if isinstance(parsed_value, dict):
                for key in ["text", "label", "value", "name"]:
                    if key in parsed_value:
                        if isinstance(parsed_value[key], dict):
                            return parsed_value[key].get("text", str(parsed_value[key]))
                        return str(parsed_value[key])
                return text if text else str(parsed_value)
            else:
                return str(parsed_value)
        except json.JSONDecodeError:
            return text if text else value

# Função para buscar todos os itens de um quadro usando items_page com paginação
@st.cache_data(ttl=1800)
def fetch_items(board_id, api_token):
    all_items = []
    cursor = None
    limit = 500  # Máximo permitido por chamada
    headers = {"Authorization": api_token}

    with st.spinner(f"Carregando itens do quadro {board_id}..."):
        while True:
            cursor_field = f', cursor: "{cursor}"' if cursor else ""
            query = f"""
            query {{
              boards(ids: [{board_id}]) {{
                items_page(limit: {limit}{cursor_field}) {{
                  cursor
                  items {{
                    id
                    name
                    group {{
                      id
                      title
                    }}
                    column_values {{
                      id
                      value
                      text
                    }}
                  }}
                }}
              }}
            }}
            """
            response = requests.post(API_URL, json={"query": query}, headers=headers)
            
            if response.status_code != 200:
                st.error(f"Erro ao buscar itens: {response.status_code} - {response.text}")
                break
                
            data = response.json()
            if not data or "data" not in data or "boards" not in data["data"] or not data["data"]["boards"]:
                break

            items_page = data["data"]["boards"][0]["items_page"]
            items = items_page.get("items", [])
            all_items.extend(items)
            cursor = items_page.get("cursor")

            if not cursor:  # Se não houver mais cursor, terminamos
                break

    return all_items

# Função para processar um item e extrair os campos desejados
def process_item(item, board_data, user_map, column_map, status_labels_map):
    group_map = {g["id"]: g["title"] for g in board_data.get("groups", [])}
    column_values = {cv["id"]: cv for cv in item.get("column_values", [])}

    # Nome do item
    name = item.get("name", "No name")

    # Grupo
    group_id = item["group"]["id"] if item.get("group") else None
    group = group_map.get(group_id, "No group") if group_id else "No group"

    # Quadro
    board = board_data.get("name", "No board")

    # Pessoas
    person_column_id = column_map.get("person_column_id")
    persons = []
    if person_column_id and person_column_id in column_values:
        value = column_values[person_column_id].get("value")
        if value:
            try:
                parsed_value = json.loads(value)
                if isinstance(parsed_value, dict) and "personsAndTeams" in parsed_value:
                    for user in parsed_value["personsAndTeams"]:
                        if user.get("kind") == "person":
                            user_id = str(user.get("id", ""))
                            persons.append(user_map.get(user_id, f"Unknown User {user_id}"))
            except json.JSONDecodeError:
                # Para casos onde o valor não é um JSON válido
                text_value = column_values[person_column_id].get("text", "")
                if text_value:
                    persons.append(text_value)
    persons = ", ".join(persons) if persons else "No person"

    # Data - usando a função genérica
    date_column_id = column_map.get("date_column_id")
    date = extract_column_value(date_column_id, "date", column_values, status_labels_map)

    # Status - usando a função genérica
    status_column_id = column_map.get("status_column_id")
    status = extract_column_value(status_column_id, "status", column_values, status_labels_map)

    # Item ID para rastreabilidade
    item_id = item.get("id", "No ID")

    return {
        "id": item_id,
        "name": name,
        "group": group,
        "board": board,
        "persons": persons,
        "date": date,
        "status": status
    }

# Função ajustada para converter datas e adicionar classificação de urgência
def process_dates_and_add_urgency(df, start_date=None, end_date=None, excluded_status=None):
    # Data atual para comparação
    today = datetime.now().date()
    
    # Criar uma cópia do DataFrame
    df_processed = df.copy()
    
    # Função auxiliar para converter data de string para objeto date
    def safe_date_conversion(date_str):
        if not date_str or date_str.startswith('No ') or not isinstance(date_str, str):
            return pd.NaT
        
        try:
            # Tentar conversão direta (formato YYYY-MM-DD esperado)
            return pd.to_datetime(date_str)
        except:
            try:
                # Tentar outros formatos comuns
                for fmt in ['%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d', '%d-%m-%Y', '%m-%d-%Y']:
                    try:
                        return pd.to_datetime(date_str, format=fmt)
                    except:
                        continue
                return pd.NaT
            except:
                return pd.NaT
    
    # Adicionar coluna de data convertida para ordenação
    df_processed['date_converted'] = df_processed['date'].apply(safe_date_conversion)
    
    # Filtrar por status (se especificado)
    if excluded_status and len(excluded_status) > 0:
        df_processed = df_processed[~df_processed['status'].isin(excluded_status)]
    
    # Filtrar por intervalo de datas (se especificado)
    if start_date and end_date:
        start_date_pd = pd.to_datetime(start_date)
        end_date_pd = pd.to_datetime(end_date)
        
        # Filtrar apenas itens com datas válidas e dentro do intervalo
        date_mask = ~pd.isna(df_processed['date_converted']) & \
                    (df_processed['date_converted'] >= start_date_pd) & \
                    (df_processed['date_converted'] <= end_date_pd)
        
        df_processed = df_processed[date_mask]
    
    # Função para classificar urgência com base nas novas regras
    def classify_urgency(row):
        date_str = row['date']
        status = row['status']
        
        # Se o status for "Feito", não classificar como Atrasado ou Atenção
        if status == "Feito":
            return None
        
        # Usar a data já convertida da nova coluna
        date_obj = row['date_converted']
        if pd.isna(date_obj):
            return None
        
        # Extrair a data como objeto date para comparação com today
        date_obj = date_obj.date() if hasattr(date_obj, 'date') else None
        if date_obj is None:
            return None
        
        # Calcular a diferença em dias entre a data do item e hoje
        days_diff = (date_obj - today).days
        
        # Regra 1: "Atrasado" - até 30 dias atrasado e status diferente de "Feito"
        if days_diff <= 0 and days_diff >= -30:
            return "Atrasado"
        
        # Regra 2: "Atenção" - até 15 dias à frente e status diferente de "Feito"
        elif days_diff > 0 and days_diff <= 15:
            return "Atenção"
        
        # Caso não se enquadre nas regras acima
        return None
    
    # Aplicar a classificação de urgência
    df_processed['urgency'] = df_processed.apply(classify_urgency, axis=1)
    
    # Ordenar por persons (ordem alfabética) e date_converted (da mais antiga para a mais nova)
    if not df_processed.empty:
        df_processed = df_processed.sort_values(
            by=['persons', 'date_converted'], 
            ascending=[True, True],
            na_position='last',
            key=lambda col: col.str.lower() if col.name == 'persons' else col
        )
    
    # Remover a coluna temporária de data convertida após a ordenação
    df_processed = df_processed.drop('date_converted', axis=1)
    
    return df_processed

# Função principal para processar todos os itens de todos os quadros
def fetch_all_items(api_token, start_date=None, end_date=None, excluded_status=None):
    # Mostrar progresso
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # Buscar todos os quadros
    status_text.text("Buscando quadros...")
    boards = fetch_all_boards(api_token)
    if not boards:
        st.error("Não foi possível obter os quadros. Verifique seu token de API.")
        return None
    
    # Buscar mapeamento de usuários
    status_text.text("Buscando usuários...")
    user_map = get_user_map(api_token)
    
    # Extrair mapeamentos de status das configurações de coluna
    status_text.text("Extraindo mapeamentos de status...")
    status_labels_map = extract_status_maps(boards)
    
    # Lista para armazenar todos os itens
    all_items = []
    
    # Contador para monitorar o progresso
    processed_boards = 0
    total_boards = len(boards)
    
    # Processar cada quadro
    for board in boards:
        processed_boards += 1
        board_id = board["id"]
        board_name = board["name"]
        
        # Log: Informar qual quadro está sendo processado
        status_text.text(f"Processando quadro {processed_boards}/{total_boards}: '{board_name}' (ID: {board_id})...")
        progress_bar.progress(processed_boards / total_boards)
        
        # Identificar colunas específicas
        columns = board.get("columns", [])
        column_map = {
            "person_column_id": identify_column(columns, "people", ["Pessoas", "Responsável", "Assignee", "Owner", "people", "responsible", "assignee", "owner", "Pessoa"])["id"] if identify_column(columns, "people", ["Pessoas", "Responsável", "Assignee", "Owner", "people", "responsible", "assignee", "owner", "Pessoa"]) else None,
            "date_column_id": identify_column(columns, "date", ["Data", "Deadline", "Due Date", "Prazo", "date", "deadline", "due date", "prazo", "PRAZO"])["id"] if identify_column(columns, "date", ["Data", "Deadline", "Due Date", "Prazo", "date", "deadline", "due date", "prazo", "PRAZO"]) else None,
            "status_column_id": identify_column(columns, "status", ["Status", "Estado", "status", "state", "STATUS"])["id"] if identify_column(columns, "status", ["Status", "Estado", "status", "state", "STATUS"]) else None,
        }
        
        # Buscar itens do quadro
        items = fetch_items(board_id, api_token)
        
        # Log: Informar quantos itens foram encontrados no quadro
        status_text.text(f"Processando quadro {processed_boards}/{total_boards}: '{board_name}' (ID: {board_id}) - {len(items)} itens encontrados.")
        
        # Processar cada item
        for item in items:
            try:
                item_data = process_item(item, board, user_map, column_map, status_labels_map)
                all_items.append(item_data)
            except Exception as e:
                st.warning(f"Erro ao processar item {item.get('id', 'desconhecido')} do quadro {board['name']}: {str(e)}")
    
    # Finalizar progresso
    progress_bar.progress(1.0)
    status_text.text("Processamento concluído!")
    
    # Converter para DataFrame e processar
    if all_items:
        df = pd.DataFrame(all_items)
        
        # Processar datas e adicionar classificação de urgência
        df_processed = process_dates_and_add_urgency(df, start_date, end_date, excluded_status)
        
        return df_processed
    else:
        st.warning("Nenhum item foi processado com sucesso.")
        return None

# Interface do Streamlit
def main():
    st.sidebar.header("Filtros")
    
    # Carregar os quadros e extrair informações de status
    if st.sidebar.button("Carregar Dados de Status"):
        with st.spinner("Carregando dados iniciais..."):
            boards = fetch_all_boards(API_TOKEN)
            status_labels_map = extract_status_maps(boards)
            all_status = get_all_status_values(boards, status_labels_map)
            
            # Armazenar no estado da sessão
            st.session_state.all_status = all_status
            st.session_state.boards_loaded = True
    
    # Inicializar o estado da sessão se necessário
    if "all_status" not in st.session_state:
        st.session_state.all_status = ["Feito", "Em Andamento", "Parado"]
    
    if "boards_loaded" not in st.session_state:
        st.session_state.boards_loaded = False
        
    # Seleção de datas
    st.sidebar.subheader("Intervalo de Data")
    start_date = st.sidebar.date_input("Data Inicial", datetime.now() - timedelta(days=30))
    end_date = st.sidebar.date_input("Data Final", datetime.now() + timedelta(days=30))
    
    # Seleção de status a excluir
    st.sidebar.subheader("Status a Desconsiderar")
    excluded_status = st.sidebar.multiselect(
        "Selecione os status que deseja excluir", 
        st.session_state.all_status, 
        default=["Feito"]
    )
    
    # Botão para buscar dados
    if st.sidebar.button("Buscar Itens"):
        if API_TOKEN:
            with st.spinner("Buscando itens do Monday.com..."):
                df = fetch_all_items(
                    API_TOKEN, 
                    start_date=start_date,
                    end_date=end_date,
                    excluded_status=excluded_status
                )
                
                if df is not None and not df.empty:
                    st.session_state.data = df
                    st.success(f"Dados carregados com sucesso! {len(df)} itens encontrados.")
                else:
                    st.warning("Nenhum item encontrado com os filtros selecionados.")
        else:
            st.error("Por favor, forneça um token de API válido.")
    
    # Botões para exportar
    col1, col2 = st.sidebar.columns(2)
    
    if col1.button("Exportar CSV"):
        if "data" in st.session_state and not st.session_state.data.empty:
            csv = st.session_state.data.to_csv(index=False, encoding="utf-8", sep=";")
            col1.download_button(
                label="Download CSV",
                data=csv,
                file_name=f"monday_items_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )
        else:
            st.sidebar.warning("Não há dados para exportar.")
    
    if col2.button("Exportar JSON"):
        if "data" in st.session_state and not st.session_state.data.empty:
            json_str = st.session_state.data.to_json(orient="records", force_ascii=False)
            col2.download_button(
                label="Download JSON",
                data=json_str,
                file_name=f"monday_items_{datetime.now().strftime('%Y%m%d')}.json",
                mime="application/json"
            )
        else:
            st.sidebar.warning("Não há dados para exportar.")
    
    # Exibir dados se disponíveis
    if "data" in st.session_state and not st.session_state.data.empty:
        df = st.session_state.data
        
        # Mostrar estatísticas
        st.subheader("Estatísticas")
        col1, col2, col3 = st.columns(3)
        col1.metric("Total de Itens", len(df))
        col2.metric("Responsáveis Únicos", df["persons"].nunique())
        
        urgent_count = df[df["urgency"] == "Atrasado"].shape[0]
        attention_count = df[df["urgency"] == "Atenção"].shape[0]
        col3.metric("Itens Atrasados/Atenção", f"{urgent_count}/{attention_count}")
        
        # Gráfico de status
        st.subheader("Distribuição por Status")
        status_counts = df["status"].value_counts()
        st.bar_chart(status_counts)
        
        # Tabela com os dados
        st.subheader("Itens")
        
        # Permitir filtrar por urgência
        urgency_filter = st.multiselect(
            "Filtrar por Urgência", 
            ["Atrasado", "Atenção", "Sem Classificação"],
            default=[]
        )
        
        # Aplicar filtro de urgência
        filtered_df = df
        if urgency_filter:
            # Substituir None por "Sem Classificação" para o filtro
            urgency_mapping = {"Atrasado": "Atrasado", "Atenção": "Atenção", "Sem Classificação": None}
            urgency_values = [urgency_mapping[u] for u in urgency_filter]
            
            # Filtrar DataFrame
            if "Sem Classificação" in urgency_filter:
                # Necessário tratar None separadamente
                filtered_df = df[df["urgency"].isin([v for v in urgency_values if v is not None]) | df["urgency"].isna()]
            else:
                filtered_df = df[df["urgency"].isin(urgency_values)]
        
        # Aplicar estilo à tabela baseado na urgência
        def highlight_urgency(val):
            if val == "Atrasado":
                return 'background-color: #FFCCCC'
            elif val == "Atenção":
                return 'background-color: #FFFFCC'
            else:
                return ''
        
        # Mostrar a tabela com highlighting
        st.dataframe(
            filtered_df.style.applymap(
                highlight_urgency, 
                subset=["urgency"]
            ),
            use_container_width=True
        )
    else:
        if not st.session_state.boards_loaded:
            st.info("Clique em 'Carregar Dados de Status' para iniciar a aplicação e carregar os status disponíveis.")
        else:
            st.info("Configure os filtros e clique em 'Buscar Itens' para visualizar os dados.")

if __name__ == "__main__":
    main()