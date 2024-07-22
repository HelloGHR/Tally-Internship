from fastapi import FastAPI, File, UploadFile,Form
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from langchain.chains.conversation.memory import ConversationBufferWindowMemory
import os
import shutil
import uuid
import json
import speech_recognition as sr
from pydantic import ValidationError
from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError

app = FastAPI()

class StreamRequest(BaseModel):
    message: str
    session_id: str

class ChatRequest(BaseModel):
    message: str
    session_id: str

# Store memory objects keyed by session_id
memory_store = {}

def get_memory(session_id):
    if session_id not in memory_store:
        memory_store[session_id] = ConversationBufferWindowMemory(k=3, memory_key="chat_history", return_messages=True)
    return memory_store[session_id]

chat = ChatGroq(
    temperature=0,
    model="llama3-70b-8192",
    api_key="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"
)

system = " आप एक दोस्ताना बातचीत करने वाले चैटबॉट हैं। कृपया केवल चार्टर्ड अकाउंटेंसी (CA) से संबंधित प्रश्नों का उत्तर दें। अन्य किसी भी विषय पर उत्तर न दें। अपने उत्तरों को 50 शब्दों के भीतर रखें। आप अभिवादन का जवाब दे सकते हैं। कृपया हिंदी में उत्तर दें।"
human = "{text}"
prompt = ChatPromptTemplate.from_messages([
    ("system", system),
    ("human", "{text}"),
    ("human", "Previous conversation:\n{chat_history}\nHuman: {text}")
])
import logging

# Function to preprocess audio using pydub for handling different formats
def preprocess_audio(audio_file_path):
    try:
        audio = AudioSegment.from_file(audio_file_path)
        temp_audio_path = "temp_processed.wav"
        audio.export(temp_audio_path, format="wav")
        return temp_audio_path
    except CouldntDecodeError as e:
        logging.error(f"Error decoding audio file: {str(e)}")
        raise ValueError("Unsupported audio format or decoding error")
    except Exception as ex:
        logging.error(f"Error processing audio file: {str(ex)}")
        raise ex

# Function for speech-to-text translation using Google Speech Recognition
def SpeechTranslation(audio_file_path):
    processed_audio_path = preprocess_audio(audio_file_path)
    r = sr.Recognizer()
    with sr.AudioFile(processed_audio_path) as source:
        audio_data = r.record(source)
        
    try:
        text = r.recognize_google(audio_data, language="hi-IN,en-US")
        print(f"Recognized text: {text}")
        return text
    except sr.UnknownValueError:
        error_msg = "Could not understand audio"
        print(error_msg)
        return error_msg
    except sr.RequestError as e:
        error_msg = f"Could not request results from Google Speech Recognition service; {e}"
        print(error_msg)
        return error_msg
    finally:
        os.remove(processed_audio_path)

# Upload file endpoint
@app.post("/uploadfile/")
async def upload_file(file: UploadFile = File(...), session_id: str = Form(...)):
    try:
        # Save the uploaded file
        if session_id is None:
            raise ValueError("Session ID is required.")  # Provide a default session ID if none is provided

        upload_dir = "temp"
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir)
        file_path = os.path.join(upload_dir, file.filename)
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        file.file.close()  # Ensure file is closed after saving

        # Process the uploaded audio file
        transcription_result = SpeechTranslation(file_path)
        print(f"Transcribed text: {transcription_result}")

        # Remove the uploaded file
        os.remove(file_path)
        print(session_id,"<---session_id")
        # Prepare ChatRequest with transcribed message and session ID
        chat_request = ChatRequest(message=transcription_result, session_id=session_id)

        # Call stream function directly
        stream_response = await stream(chat_request)
        return stream_response
    
    except Exception as e:
        logging.error(f"Error in upload_file: {str(e)}")
        return JSONResponse(content={"error": str(e)}, status_code=500)
    
import logging

@app.post("/transcribe/")
async def transcribe_file(file: UploadFile = File(...), session_id: str = Form(...)):
    try:
        if session_id is None:
            raise ValueError("Session ID is required.")

        upload_dir = "temp"
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir)
        file_path = os.path.join(upload_dir, file.filename)
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        file.file.close()

        # Log file path for debugging
        logging.info(f"Processing file: {file_path}")

        # Process the uploaded audio file
        transcription_result = SpeechTranslation(file_path)  # Ensure this is a correct call
        print(f"Transcribed text: {transcription_result}")

        os.remove(file_path)

        return JSONResponse(content={"transcription": transcription_result})

    except Exception as e:
        logging.error(f"Error in transcribe_file: {str(e)}")
        return JSONResponse(content={"error": str(e)}, status_code=500)

# api endpoint for getting the response with streaming
@app.post("/stream")
async def stream(request: StreamRequest):
    session_id = request.session_id
    memory = get_memory(session_id)

    conversation = memory.load_memory_variables({})
    human_message = request.message
    chat_history = conversation.get("chat_history", [])

    # Format the prompt
    messages = prompt.format_messages(text=human_message, chat_history=chat_history)

    # Generate the response
    response_chunks = chat.stream(messages)
    
    async def generate():
        full_response = ""
        for chunk in response_chunks:
            full_response += chunk.content
            yield json.dumps({"content": chunk.content}) + "\n"
        
        # Update memory with new message and response
        memory.save_context({"text": human_message}, {"output": full_response})

    return StreamingResponse(generate(), media_type="application/json")

# Reset conversation endpoint
@app.post("/reset_conversation/{session_id}")
async def reset_conversation(session_id: str):
    if session_id in memory_store:
        del memory_store[session_id]
    return {"message": "Conversation reset successfully"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
