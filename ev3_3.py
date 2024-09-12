import base64
import io
import re

import paramiko
from PIL import Image
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from paramiko import SSHClient
from scp import SCPClient

import streamlit as st

st.set_page_config(page_title="EV3 Chatbot", page_icon="🤖")

st.title("EV3 Chatbot")

custom_css = """
<style>
.cut {
    color: LightCoral;
    text-decoration: line-through;
}

.add {
    font-weight: bold;
    color: LightGreen;
}
</style>
"""

st.markdown(custom_css, unsafe_allow_html=True)


def remove_prefix(text):
    return re.sub(r'^[\w\s]+:\s*', '', text)


# Function to replace markdown with HTML tags using regular expressions
def replace_markdown(text, marker, css_class):
    pattern = re.escape(marker) + '(.*?)' + re.escape(marker)
    replacement = rf"<span class='{css_class}'>\1</span>"
    return re.sub(pattern, replacement, text)


# Function to process message content
def process_message_content(content):
    # Replace ** for bold text
    content = replace_markdown(content, "**", "cut")
    # Replace ## for header text
    content = replace_markdown(content, "##", "add")
    return content


if "chat_history" not in st.session_state:
    st.session_state.chat_history = []


def create_ssh_client(server, port, user, password):
    client = SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(server, port, user, password)
    return client


def transfer_and_execute_script(hostname, port, username, password, local_path, remote_path):
    # Create SSH client
    ssh = create_ssh_client(hostname, port, username, password)

    try:
        # SCPCLient takes a paramiko transport as an argument
        with SCPClient(ssh.get_transport()) as scp:
            # Transfer file to EV3
            scp.put(local_path, remote_path)
            print("File transferred successfully")

        # Execute the script on the EV3
        stdin, stdout, stderr = ssh.exec_command(f'python3 {remote_path}')
        print("Output:", stdout.read().decode())
        print("Errors:", stderr.read().decode())
    finally:
        # Close SSH connection
        ssh.close()


# Define connection details
ev3_hostname = 'ev3dev'
ev3_port = 22
ev3_username = 'robot'
ev3_password = 'maker'

# Define script locations
local_script_path = 'movement.py'
remote_script_path = '/home/robot/E/movement.py'


def extract_within_backticks(text):
    # Regular expression to match content within triple backticks
    pattern = r'```python(.*?)```'
    matches = re.findall(pattern, text, re.DOTALL)
    if matches != []:
        return matches[0].strip()
    else:
        return text


def get_response(query):
    llm_model = "gpt-4o"
    prompt = """
        You need to generate python code to control ev3 robot
        Please follow the tips I provided: 
        1. The robot has two wheels(large motors, port A for right wheel and B for left wheel)
        a medium motor connected to port D, an infrared sensor connected to port 4, 
        a downward color sensor connected to port 2,
        an upper color sensor connected to port 3 and a touch sensor connected to port 1. 
        2. If you want to make any turns, for example, an x degrees' turn, you let x*5=5x degrees and you just set
        the angle parameter to be 5x degrees. Please use "tank = MoveTank(OUTPUT_B, OUTPUT_A)" and "tank.on_for_degrees(-50, 50, ...)".
        And also, tank.on_for_degrees(-50, 50, ...) for left turns and tank.on_for_degrees(50, -50, ...) for right turns.
        3. If you want to go forward for certain meters, for example, 1 meter, you set he speed of wheels to be 50 and then
        set the moving time to be 1*10=10 seconds; for 0.5 meter, set speed as 50 and moving time as 0.5*10=5 seconds.
        4. When you use color sensor or infrared sensor, remember to add "" to the number inside the function(for example, use ColorSensor("3") but not ColorSensor(3))
        5. Any time you have something not clear about the instruction you can set it to a small value(for example the user doesn't tell you 
        the distance you should go or any other parameters you need, just set it small.
        6. The last thing you need to pay attention to is that in the process of answering, please only answer the specific code, and do not reply to unnecessary messages.
        Don't add any comments and generate a new code based on the prompts in the user_input.
        Please generate a new code(always add
        "#!/usr/bin/env python3
        from ev3dev2.motor import LargeMotor, MediumMotor, OUTPUT_A, OUTPUT_B, OUTPUT_D, MoveTank
        from ev3dev2.sensor.lego import TouchSensor, ColorSensor
        from ev3dev2.sound import Sound
        from time import sleep"
        at the beginning):

    The following is the action I want to perform, please change the relevant code block according to the action I enter (other unrelated code blocks are deleted, leaving only the code module related to the action I want to perform),
    Finally give me a pure executable code, without any other superfluous replies:
    {user_input}
    """
    template = ChatPromptTemplate.from_template(prompt)
    llm = ChatOpenAI(
        temperature=0.7,
        model=llm_model,
        #set up your openai_api_key here
    )
    chain = template | llm | StrOutputParser()

    return chain.invoke({
        "user_input": query
    })


def get_answer(query):
    llm_model = "gpt-4o"
    prompt = """
        if the user input is pure python code, say and only say 'Yes.'.
        if the user input isn't python code, say and only say 'No.'.
        user input: {user_input}
    """
    template = ChatPromptTemplate.from_template(prompt)
    llm = ChatOpenAI(
        temperature=0.7,
        model=llm_model,
        #set up your openai_api_key here
    )
    chain = template | llm | StrOutputParser()

    return chain.invoke({
        "user_input": query
    })


def get_description(user_query, image_data):
    llm_model = "gpt-4o"
    llm = ChatOpenAI(
        temperature=0.7,
        model=llm_model,
        #set up your openai_api_key here
    )
    message = HumanMessage(
        content=[
            {"type": "text", "text": f"Please generate code according to the image and instructions given by the user. Remember you are controlling ev3."
                                     f"Please follow the tips I provided: "
        f"1. The robot has two wheels(large motors, port A for right wheel and B for left wheel)"
        f"a medium motor connected to port D, an infrared sensor connected to port 4, "
        f"a downward color sensor connected to port 2,"
        f"an upper color sensor connected to port 3 and a touch sensor connected to port 1." 
        f"2. If you want to make any turns, for example, a 120 degrees' turn, you let 120*5=600 degrees and you just set"
        f"the angle parameter to be 600 degrees. Please use 'tank = MoveTank(OUTPUT_B, OUTPUT_A)' and 'tank.on_for_degrees(-50, 50, 600)'."
        f"3. If you want to go forward for certain meters, for example, 1 meter, you set he speed of wheels to be 50 and then"
        f"set the moving time to be 1*10=10 seconds; for 0.5 meter, set speed as 50 and moving time as 0.5*10=5 seconds."
        f"4. When you use color sensor or infrared sensor, remember to add "" to the number inside the function(for example, use ColorSensor('3') but not ColorSensor(3))"
        f"5. Any time you have something not clear about the instruction you can set it to a small value(for example the user doesn't tell you "
        f"the distance you should go or any other parameters you need, just set it small)"
        f"6. The last thing you need to pay attention to is that in the process of answering, please only answer the specific code, and do not reply to unnecessary messages."
        f"Don't add any comments and generate a new code based on the prompts in the user_input."
        f"Please generate a new code(always add"
        f"'#!/usr/bin/env python3"
        f"from ev3dev2.motor import LargeMotor, MediumMotor, OUTPUT_A, OUTPUT_B, OUTPUT_D, MoveTank"
        f"from ev3dev2.sensor.lego import TouchSensor, ColorSensor"
        f"from ev3dev2.sound import Sound"
        f"from time import sleep'"
        f"at the beginning) "
                                     f"{user_query}"},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_data}"},
            },
        ],
    )
    return llm.invoke([message]).content


if not st.session_state.chat_history:
    st.session_state.chat_history.append(AIMessage("Hello! I'm EV3! 😎"))

# conversation
for message in st.session_state.chat_history:
    if isinstance(message, HumanMessage):
        with st.chat_message("Human", avatar="🤓"):
            st.markdown(process_message_content(message.content), unsafe_allow_html=True)
    elif isinstance(message, AIMessage):
        with st.chat_message("AI", avatar="👽"):
            st.markdown(process_message_content(message.content), unsafe_allow_html=True)
    elif isinstance(message, Image.Image):
        with st.chat_message("Human", avatar="🤓"):
            st.image(message, caption='Decoded Image')

user_query = st.chat_input("say something!!!")
uploaded_file = st.file_uploader("Choose a file")

# Initialize the state variable if it doesn't exist
if 'button_clicked' not in st.session_state:
    st.session_state['button_clicked'] = False

if user_query is not None and user_query != "":
    if uploaded_file is not None:
        bytes_data = uploaded_file.getvalue()
        image_data = base64.b64encode(bytes_data).decode("utf-8")
        try:
            # Decode the base64 string
            image_data_decode = base64.b64decode(image_data)

            # Convert to bytes and create an image
            image = Image.open(io.BytesIO(image_data_decode))

        except Exception as e:
            st.error(f"An error occurred: {e}")

        st.session_state.chat_history.append(image)
        st.session_state.chat_history.append(HumanMessage(user_query))

        with st.chat_message("Human", avatar="🤓"):
            # Display the image in Streamlit
            st.image(image, caption='Decoded Image')
            st.markdown(user_query)

        with open("movement.py", "w") as file:
            response = get_description(user_query, image_data)
            print(response)
            response_cut = extract_within_backticks(response)
            code_or_not = get_answer(response_cut)
            print(code_or_not)
            if code_or_not == "Yes.":
                file.write(response_cut)
                print("file created/overridden")
                # Set the state variable to True after the send button is clicked
                st.session_state['button_clicked'] = True

                with st.chat_message("AI", avatar="👽"):
                    ai_response = "great! now you can try and run the program!"
                    st.markdown(ai_response)
            else:
                with st.chat_message("AI", avatar="👽"):
                    ai_response = response_cut
                    st.markdown(ai_response)

        st.session_state.chat_history.append(AIMessage(ai_response))
        st.rerun()
    else:
        st.session_state.chat_history.append(HumanMessage(user_query))

        with st.chat_message("Human", avatar="🤓"):
            processed_query = process_message_content(user_query)
            st.markdown(processed_query, unsafe_allow_html=True)

        with open("movement.py", "w") as file:
            response = get_response(user_query)
            response_cut = extract_within_backticks(response)
            code_or_not = get_answer(response_cut)
            print(code_or_not)
            if code_or_not == "Yes.":
                file.write(response_cut)
                print("file created/overridden")
                # Set the state variable to True after the send button is clicked
                st.session_state['button_clicked'] = True

                with st.chat_message("AI", avatar="👽"):
                    ai_response = "great! now you can try and run the program!"
                    st.markdown(ai_response)
            else:
                with st.chat_message("AI", avatar="👽"):
                    ai_response = response_cut
                    st.markdown(ai_response)

        st.session_state.chat_history.append(AIMessage(ai_response))

# Check the state variable to decide whether to show the run button
if st.session_state['button_clicked']:
    if st.button("run"):
        print("program running!")
        try:
            transfer_and_execute_script(ev3_hostname, ev3_port, ev3_username, ev3_password, local_script_path,
                                        remote_script_path)  # Run the function to transfer and execute
        except Exception as e:
            print(e)
            with st.chat_message("AI", avatar="👽"):
                ai_response = "sorry, something went wrong 😭"
                st.markdown(ai_response)
            st.session_state.chat_history.append(AIMessage(ai_response))





