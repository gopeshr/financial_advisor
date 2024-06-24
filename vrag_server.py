from vertexai.preview import rag
from vertexai.preview.generative_models import GenerativeModel, Tool
from fastapi import FastAPI, WebSocket, File, UploadFile, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import vertexai
import os
import json
from google.cloud import storage
import uvicorn
import shutil
import base64
from pydantic import BaseModel

os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = "google-sevice-account.json"

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
 
# websocket_accept = False

with open("bucket_mapping.json") as file:
    bucket = json.load(file)
    
def delete_corpus(corpus_name):
    try:
        rag.delete_corpus(name=corpus_name)
        return f"{corpus_name} deleted successfully"
    except:
        return f"Couldn't delete {corpus_name}"

def create_corpus(selected_files: list[str]):
    try:
        rag_corpus = rag.create_corpus(display_name="f_advisorv1")
        bucket_url_list = []
        for file in selected_files:
            bucket_url_list.append(bucket[file])
        
        response = rag.import_files(
        rag_corpus.name,
        bucket_url_list,
        chunk_size=3000,  
        chunk_overlap=100,
        )
        return "Files imported to Corpus successfully.", rag_corpus
    except:
        return "Error creating corpus. Check for file limit.", None

def init_retrieval(corpus_name):
    rag_retrieval_tool = Tool.from_retrieval(
    retrieval=rag.Retrieval(
        source=rag.VertexRagStore(
            rag_corpora=[corpus_name],  # Currently only 1 corpus is allowed.
            similarity_top_k=3,  # Optional
            ),
        )
    )
    return rag_retrieval_tool

def init_model(rag_retrieval_tool):
    rag_model = GenerativeModel(
    model_name="gemini-1.0-pro-002", tools=[rag_retrieval_tool]
    )
    return rag_model

def download_blob(bucket_name, source_blob_name, destination_file_name):
    """Downloads a blob from the bucket."""
    storage_client = storage.Client.from_service_account_json('lumen-b-ctl-047-e2aeb24b0ea0.json')
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(source_blob_name)

    blob.download_to_filename(destination_file_name)

    print(f"Blob {source_blob_name} downloaded to {destination_file_name}.")

def empty_folder(folder_path: str):
    if os.path.exists(folder_path) and os.path.isdir(folder_path):
        for filename in os.listdir(folder_path):
            file_path = os.path.join(folder_path, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)  # Remove the file or link
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)  # Remove the directory and its contents
            except Exception as e:
                return f'Failed to delete {file_path}. Reason: {e}'
        return f"Folder '{folder_path}' has been emptied."
    else:
        return f"Folder '{folder_path}' not found."

@app.websocket("/ws")
async def financial_advisor(websocket: WebSocket):
    await websocket.accept()
    empty_folder("selected_documents")
    selected_files = await websocket.receive_text()
    selected_files = selected_files.split(",")
    for file in selected_files:
        if file == "":
            selected_files.remove(file)
    # corpus_list = rag.list_corpora()
    # for corpus in corpus_list:
    #     print(delete_corpus(corpus.name))
    for file in selected_files:
        download_blob("rag-test_bucket", file, f"selected_documents/{file}")
    pdf_b64 = []
    for file in selected_files:
        with open(f"selected_documents/{file}", "rb") as pdf_file:
            encoded_string = base64.b64encode(pdf_file.read())
            await websocket.send_text(encoded_string)
    corpus_status, rag_corpus = create_corpus(selected_files)
    
    # await websocket.send_text(corpus_status)
    if corpus_status == "Error creating corpus. Check for file limit.":
        await websocket.send_text(corpus_status)
        await financial_advisor(websocket)
    else:
        try:
            rag_retrieval_tool = init_retrieval(rag_corpus.name)
        except:
            await websocket.send_text("Error initializing retrieval tool.")
            await financial_advisor(websocket)
    rag_model = init_model(rag_retrieval_tool)
    await websocket.send_text("Documents Loaded. Start your chat!")
    while True:
        user_query = await websocket.receive_text()
        response = rag_model.generate_content(user_query)
        await websocket.send_text(response.text)

if __name__ == "__main__":
    uvicorn.run(app)