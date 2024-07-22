import streamlit as st
import requests
import json
from streamlit_chat import message
from gtts import gTTS
import io
import uuid
from streamlit_mic_recorder import mic_recorder

st.set_page_config(initial_sidebar_state="expanded")
with open("style.css") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# Initialize session state variables
if "conversations" not in st.session_state:
    st.session_state.conversations = {}
if "current_conversation_id" not in st.session_state:
    st.session_state.current_conversation_id = None
if "stream_complete" not in st.session_state:
    st.session_state.stream_complete = True
if "audio_data" not in st.session_state:
    st.session_state.audio_data = None
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "processing_audio" not in st.session_state:
    st.session_state.processing_audio = False
if "audio_to_process" not in st.session_state:
    st.session_state.audio_to_process = None
if "audio_processed" not in st.session_state:
    st.session_state.audio_processed = False
if "audio_cache" not in st.session_state:
    st.session_state.audio_cache = {}

# Function to create a new conversation
def new_conversation():
    conversation_id = str(uuid.uuid4())
    st.session_state.conversations[conversation_id] = []
    st.session_state.current_conversation_id = conversation_id
    requests.post(f"http://localhost:8000/reset_conversation/{conversation_id}")

# Create a new conversation if none exists
if not st.session_state.conversations:
    new_conversation()

# Sidebar for conversation history
with st.sidebar:
    st.title("Your AI BUDDY")
    
    # New Chat button
    if st.button("New Chat"):
        new_conversation()
        st.experimental_rerun()
    
    # Display conversation history
    st.subheader("Chat History")
    for conv_id, messages in st.session_state.conversations.items():
        if messages:
            # Display the first user message as the conversation title
            title = next((m[1] for m in messages if m[0] == "assistant"), "New Chat")
            if st.button(f"{title[:30]}...", key=f"conv_{conv_id}"):
                st.session_state.current_conversation_id = conv_id
                st.experimental_rerun()

# Function to send a message to the API and retrieve the response
def send_message_to_api(message, history, session_id):
    url = "http://localhost:8000/stream"
    response = requests.post(url, json={"message": message, "history": history, "session_id": session_id}, stream=True)
    if response.status_code == 200:
        for line in response.iter_lines():
            if line:
                try:
                    response_json = json.loads(line.decode('utf-8'))
                    yield response_json.get("content", "")
                except ValueError:
                    st.write("Error: Invalid response format")
                    yield "Error: Invalid response format"
    else:
        yield f"Error: {response.status_code} - {response.reason}"

# Function to convert text to speech
def text_to_speech(text, lang='hi'):
    tts = gTTS(text=text, lang=lang, slow=False)
    audio_bytes = io.BytesIO()
    tts.write_to_fp(audio_bytes)
    audio_bytes.seek(0)
    return audio_bytes

# Function to play audio
def play_audio_response(text, lang='hi'):
    if text not in st.session_state.audio_cache:
        with st.spinner(''):
            audio_bytes = text_to_speech(text, lang)
            st.session_state.audio_cache[text] = audio_bytes
    else:
        audio_bytes = st.session_state.audio_cache[text]
    st.audio(audio_bytes, format="audio/mp3")

# Function to display messages
def display_messages():
    message_container = st.container()
    current_messages = st.session_state.conversations[st.session_state.current_conversation_id]
    
    # Group messages into exchanges (user + assistant)
    exchanges = []
    for i in range(0, len(current_messages), 2):
        if i + 1 < len(current_messages):
            exchanges.append((current_messages[i], current_messages[i+1]))
        else:
            exchanges.append((current_messages[i], None))
    
    # Reverse the order of exchanges to show latest first
    exchanges.reverse()
    
    # Display messages
    for i, (user_message, assistant_message) in enumerate(exchanges):
        with message_container:
            if user_message:
                message(user_message[1], is_user=True, key=f"user_{i}")
            if assistant_message:
                message(assistant_message[1], is_user=False, key=f"assistant_{i}")
                if st.button("🔊", key=f"play_{i}"):
                    play_audio_response(assistant_message[1], lang='hi')

display_messages()

# Main code
input_container = st.container()

# Use the container for input
with input_container:
    col1, col2 = st.columns([0.9, 0.1])
    with col1:
        if st.session_state.processing_audio:
            st.write("Processing audio, please wait...")
        else:
            user_input = st.chat_input("Type your message here...", key="user_input")

    with col2:
        audio = mic_recorder(start_prompt="🎙", stop_prompt="🔴", key='recorder')

# Check for new audio input
if audio is not None and audio != st.session_state.audio_data:
    st.session_state.audio_to_process = audio
    st.session_state.audio_processed = False
    st.session_state.audio_data = audio

# Process text input
if user_input and not st.session_state.processing_audio and st.session_state.stream_complete:
    st.session_state.stream_complete = False
    current_messages = st.session_state.conversations[st.session_state.current_conversation_id]
    current_messages.append(("user", user_input))
    
    # Prepare history for API
    history = [(role, content) for role, content in current_messages[:-1]]
    
    # Call the API and get the assistant response
    with st.spinner("Processing your request..."):
        response_placeholder = st.empty()  # Placeholder for streaming response
        full_response = ""
        for response_chunk in send_message_to_api(user_input, history, st.session_state.current_conversation_id):
            full_response += response_chunk
            response_placeholder.write(full_response)
    
    # Add assistant response to current conversation
    current_messages.append(("assistant", full_response))
    
    st.session_state.stream_complete = True
    st.experimental_rerun()

# Process audio input
if st.session_state.audio_to_process is not None and not st.session_state.processing_audio and not st.session_state.audio_processed:
    st.session_state.processing_audio = True
    audio_data = st.session_state.audio_to_process['bytes']
    
    # Save the audio file temporarily
    with open("temp_audio.webm", "wb") as f:
        f.write(audio_data)

    current_messages = st.session_state.conversations[st.session_state.current_conversation_id]
    #current_messages.append(("user", "You gave audio"))

    # Process the audio file by sending it to FastAPI
    files = {'file': open("temp_audio.webm", "rb")}
    data = {'session_id': st.session_state.session_id}
    upload_response1 = requests.post("http://localhost:8000/transcribe/", files=files, data=data)
    
    if upload_response1.status_code == 200:
        response_json = upload_response1.json()
        transcription_result = response_json.get("transcription", "")
        
        if transcription_result:
            # Send the transcription result to the streaming API
            current_messages.append(("user", transcription_result))
            
            # Prepare history for API
            history = [(role, content) for role, content in current_messages[:-1]]
            
            full_response = ""
            with st.spinner("Tally Ai Hindi में आपका स्वागत है!!"):
                response_placeholder = st.empty()  # Placeholder for streaming response
                for response_chunk in send_message_to_api(transcription_result, history, st.session_state.session_id):
                    full_response += response_chunk
                    response_placeholder.write(full_response)
            
            # Add assistant response to current conversation
            current_messages.append(("assistant", full_response))
        else:
            st.write("No transcription result received from the server.")
    else:
        st.write(f"Error: {upload_response1.status_code} - {upload_response1.reason}")
    
    # Reset the processing flag and audio data
    st.session_state.processing_audio = False
    st.session_state.audio_to_process = None
    st.session_state.audio_processed = True
    st.experimental_rerun()

# Check for session ID in JavaScript
st.markdown(
    """
    <script>
        var session_id = sessionStorage.getItem('session_id');
        if (session_id === null) {
            session_id = '%s';
            sessionStorage.setItem('session_id', session_id);
        }
        if (session_id !== '%s') {
            sessionStorage.setItem('session_id', '%s');
            window.location.reload();
        }
    </script>
    """ % (st.session_state.session_id, st.session_state.session_id, st.session_state.session_id),
    unsafe_allow_html=True
)
