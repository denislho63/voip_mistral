# Mistral Voice

A small, dependency-free browser app for chatting with Mistral by voice or text. It uses your browser's speech recognition and speech synthesis, and sends chat requests directly to the Mistral API.

## Use

1. Create an API key in your [Mistral account](https://console.mistral.ai/).
2. Serve this directory locally (microphone access requires localhost or HTTPS):

   ```bash
   python3 -m http.server 8000
   ```

3. Open [http://localhost:8000](http://localhost:8000), enter your API key, and allow microphone access when prompted.
4. Tap the microphone to dictate a message, or type one and press **Send**. Replies can be read aloud; turn that off with the checkbox.

Voice recognition depends on browser support (for example, current Chrome). You can still use text chat in browsers without it.

## API key and privacy

The API key is kept only in the open page and sent from your browser to `api.mistral.ai`. It is not saved by the app or sent to a separate server. Do not use a personal API key on an untrusted or shared browser, and do not publish this page with a shared key embedded in it.