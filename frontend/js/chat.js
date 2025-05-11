/**
 * Main script for the chat page.
 * Handles WebSocket connections, sending/receiving messages,
 * and updating the UI based on server events.
 */
document.addEventListener('DOMContentLoaded', () => {
    console.log("Chat script loaded.");

    // --- UI Elements ---
    // Get references to necessary DOM elements
    const statusDiv = document.getElementById('status');
    const playerIdDisplay = document.getElementById('playerIdDisplay');
    const playerNameDisplay = document.getElementById('playerNameDisplay');
    const messagesDiv = document.getElementById('messages');
    const messageInput = document.getElementById('messageInput');
    const sendButton = document.getElementById('sendButton');

    // Check if essential elements exist
    if (!messagesDiv || !messageInput || !sendButton || !playerIdDisplay || !playerNameDisplay) {
        console.error("Missing essential DOM elements for chat. Aborting script execution.");
        // Display an error message to the user or redirect
        // alert("Error loading chat interface. Please try logging in again.");
        // window.location.href = '/login'; // Uncomment to redirect on error
        return; // Stop script execution if elements are missing
    }

    // --- WebSocket Connection ---
    let websocket = null;

    // --- Global Error Handling ---
    // Catch any uncaught errors that might occur
    window.onerror = function (message, source, lineno, colno, error) {
        console.error("Global JS Error:", message, "in", source, "line:", lineno, "col:", colno, "Error Object:", error);
        // You might want to display a user-friendly error message here
        return false; // Allow default error handling (e.g., logging to console)
    };

    // Catch unhandled promise rejections
    window.addEventListener('unhandledrejection', function (event) {
        console.error("Global Unhandled Promise Rejection:", event.reason);
    });

    // --- Get session_id ---
    // Get the session ID from the URL query parameters
    const urlParams = new URLSearchParams(window.location.search);
    const sessionId = urlParams.get('session_id');

    // --- Validate Session ID ---
    if (!sessionId) {
        console.error("No session ID found in URL. Redirecting to login.");
        // Redirect to login page if session ID is missing
        setTimeout(() => {
            window.location.href = '/login';
        }, 2000); // Give a moment to see the console error
        return; // Stop script execution
    }

    // --- Build WebSocket URL ---
    // Determine WebSocket protocol based on HTTP protocol (ws or wss)
    let wsProtocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
    let wsHost = window.location.host;
    let wsPath = '/ws';
    let wsQuery = window.location.search; // Include session_id in the query

    const websocketUrl = `${wsProtocol}${wsHost}${wsPath}${wsQuery}`;

    console.log(`Attempting to connect via WebSocket using URL: ${websocketUrl}`);

    /**
     * Establishes the WebSocket connection to the server.
     */
    function connectWebSocket() {
        // Close existing connection if it exists and is open
        if (websocket && websocket.readyState !== WebSocket.CLOSED && websocket.readyState !== WebSocket.CLOSING) {
            console.warn("Existing WebSocket connection found. Closing before creating new one.");
            websocket.close(1000, "Client reconnecting"); // Code 1000: Normal Closure
        }

        try {
            // Create a new WebSocket instance
            websocket = new WebSocket(websocketUrl);
            console.log("WebSocket object created.");

            // --- WebSocket Event Handlers ---

            websocket.onopen = function (event) {
                console.log("WebSocket connection opened.", event);
                // Update connection status indicator
                if (statusDiv) {
                    statusDiv.textContent = 'Connected';
                    statusDiv.style.color = 'green';
                }
                // UI elements (input/button) are typically enabled after receiving chat_history
            };

            websocket.onmessage = function (event) {
                // console.log("Raw message received:", event.data); // Optional: Log raw data
                try {
                    // Parse the JSON message from the server
                    const message = JSON.parse(event.data);
                    // console.log("Parsed message:", message); // Optional: Log parsed message

                    // --- Message Type Handling ---
                    switch (message.type) {
                        case 'session_terminated':
                            console.log("Received session_terminated message.");
                            // Inform the user and prepare for redirect
                            appendMessage(`<em>${message.message || "Your session has been taken over."}</em>`, 'system-message');

                            // Disable input elements
                            if (messageInput) messageInput.disabled = true;
                            if (sendButton) sendButton.disabled = true;

                            // Explicitly close the websocket if it's still open
                            if (websocket && websocket.readyState === WebSocket.OPEN) {
                                console.log("Closing websocket explicitly due to session_terminated.");
                                websocket.close(1000, "Session terminated by server");
                            }

                            // Redirect to login page after a short delay
                            console.log("Redirecting to /login due to session_terminated.");
                            setTimeout(() => { window.location.href = '/login'; }, 3000);
                            return; // Stop further processing of this message

                        case 'chat_history':
                            console.log(`Received chat_history (${message.messages ? message.messages.length : 0} messages).`);
                            appendMessage(`<em>--- Chat History ---</em>`, 'system-message');
                            // Clear current messages before displaying history
                            if (messagesDiv) messagesDiv.innerHTML = '';

                            if (message.messages && Array.isArray(message.messages)) {
                                // Sort history by timestamp (optional, server might sort)
                                message.messages.sort((a, b) => a.timestamp - b.timestamp);

                                message.messages.forEach(msg => {
                                    // Only append chat messages from history
                                    if (msg.type === 'chat_message') {
                                        appendMessage(`<strong>${msg.sender}:</strong> ${msg.text}`);
                                    }
                                });
                            }
                            appendMessage(`<em>--- End History ---</em>`, 'system-message');

                            // History received, enable input elements
                            if (messageInput) messageInput.disabled = false;
                            if (sendButton) sendButton.disabled = false;
                            if (messageInput) messageInput.focus(); // Set focus to input field

                            break;

                        case 'player_joined':
                            console.log("Received player_joined message.");
                            // Display a system message about a player joining
                            const joinedPlayerName = message.name || message.permanent_user_id || "A player";
                            const totalPlayers = message.totalPlayers;
                            appendMessage(`<em>${joinedPlayerName} joined the chat. Total players: ${totalPlayers}</em>`, 'system-message');
                            // Optional: Update a separate player list UI element here if you have one

                            break;

                        case 'player_left':
                            console.log("Received player_left message.");
                            // Display a system message about a player leaving
                            const leftPlayerName = message.name || message.permanent_user_id || message.player_id || "A player";
                            const remainingPlayers = message.remaining_players;
                            appendMessage(`<em>${leftPlayerName} left the chat. Remaining players: ${remainingPlayers}</em>`, 'system-message');
                            // Optional: Update a separate player list UI element here

                            break;

                        case 'chat_message':
                            console.log("Received chat_message.");
                            // Display a standard chat message
                            if (message.sender && message.text) {
                                appendMessage(`<strong>${message.sender}:</strong> ${message.text}`);
                            } else {
                                console.warn("Received incomplete chat_message:", message);
                            }
                            break;

                        case 'server_error':
                            console.error("Received server_error:", message.message);
                            appendMessage(`<strong>Error:</strong> ${message.message}`, 'system-message');
                            break;

                        case 'player_error':
                            console.warn("Received player_error:", message);
                            appendMessage(`<strong>Warning:</strong> An error occurred with ${message.name || message.permanent_user_id || message.player_id || "a player"}'s connection.`, 'system-message');
                            break;

                        case 'error': // Specific backend error (e.g., invalid session on WS connect)
                            console.error("Received connection error from server:", message.message);
                            appendMessage(`<strong>Connection Rejected:</strong> ${message.message}`, 'system-message');
                            // Redirect to login page as connection was rejected
                            setTimeout(() => { window.location.href = '/login'; }, 3000);
                            break;

                        default:
                            // Log and ignore unknown message types
                            console.warn("Received message with unknown type:", message.type, message);
                            break;
                    }

                } catch (e) {
                    console.error("Failed to parse message as JSON or process message:", e);
                    // Display an error message if parsing or processing fails
                    appendMessage(`<em>Failed to process message:</em> ${event.data}`, 'system-message');
                }
            };

            websocket.onerror = function (event) {
                console.error("WebSocket error observed:", event);
                // Update connection status and display error message
                if (statusDiv) {
                    statusDiv.textContent = 'Error';
                    statusDiv.style.color = 'red';
                }
                appendMessage("<em>WebSocket Error! Connection failed or interrupted.</em>", 'system-message');
                // Disable input on error
                if (messageInput) messageInput.disabled = true;
                if (sendButton) sendButton.disabled = true;
                // Update player info display to indicate error if necessary
                // if (playerNameDisplay) playerNameDisplay.textContent = "Error";
                // if (playerIdDisplay) playerIdDisplay.textContent = "Error";
            };

            websocket.onclose = function (event) {
                console.log("WebSocket connection closed:", event.code, event.reason);
                // Update connection status
                if (statusDiv) {
                    statusDiv.textContent = 'Disconnected';
                    statusDiv.style.color = 'orange';
                }

                // Determine the reason for closure and display a message
                let reason = event.reason || "Unknown reason";
                let closeMessage = `<em>WebSocket connection closed (${event.code}): ${reason}</em>`;

                if (event.code === 1000) {
                    closeMessage = `<em>WebSocket connection closed: ${reason}</em>`; // Normal closure
                } else if (event.code === 1008) {
                    closeMessage = `<em>Connection rejected: ${reason || "Policy violation"}. Please log in again.</em>`;
                } else if (event.code === 1006) {
                    closeMessage = `<em>WebSocket connection lost.</em>`; // Abnormal closure
                }
                // Add other specific codes if needed (like your custom 4001)
                else if (event.code === 4001) {
                    closeMessage = `<em>Connection rejected: ${reason || "Authentication failed"}. Please log in again.</em>`;
                }


                // Append the close message to the UI
                appendMessage(closeMessage, 'system-message');

                // Disable input elements
                if (messageInput) messageInput.disabled = true;
                if (sendButton) sendButton.disabled = true;

                // Optional: Attempt to reconnect after a delay if it's an unexpected closure code
                // if (event.code !== 1000 && event.code !== 1008 && event.code !== 4001) {
                //     console.log("Attempting to reconnect in 5 seconds...");
                //     setTimeout(connectWebSocket, 5000);
                // }
            };

        } catch (e) {
            // Handle errors that occur when creating the WebSocket object itself
            console.error("Error creating WebSocket object:", e);
            if (statusDiv) {
                statusDiv.textContent = 'Connection Failed';
                statusDiv.style.color = 'red';
            }
            appendMessage(`<em>Failed to connect to chat server.</em>`, 'system-message');
        }
    }

    /**
     * Updates the player ID and Name display from template values.
     */
    function updatePlayerInfoDisplay() {
        // Get values potentially pre-filled by the server template
        const templatePlayerId = playerIdDisplay.textContent;
        const templatePlayerName = playerNameDisplay.textContent;

        // If template values are meaningful, update the display
        if (templatePlayerId && templatePlayerId.trim() !== '' && templatePlayerId !== 'Connecting...') {
            playerIdDisplay.textContent = templatePlayerId;
            playerNameDisplay.textContent = templatePlayerName;
            console.log(`Player info updated from template: ID=${templatePlayerId.trim()}, Name=${templatePlayerName.trim()}`);
        } else {
            console.log("Player info from template not yet available or is default.");
            // Keep 'Connecting...' or default text
        }
    }

    /**
     * Retrieves the current player's permanent user ID from the display element.
     * Note: This relies on the playerIdDisplay being correctly set by the template.
     */
    function getPermanentUserIdFromSession() {
        return playerIdDisplay.textContent;
    }

    // --- UI Event Handlers ---

    // Send message when the send button is clicked
    if (sendButton) {
        sendButton.onclick = function () {
            sendMessage();
        };
    }

    // Send message when Enter key is pressed in the input field
    if (messageInput) {
        messageInput.addEventListener("keypress", function (event) {
            if (event.key === "Enter") {
                event.preventDefault(); // Prevent default Enter key behavior (newline)
                sendMessage();
            }
        });
    }

    /**
     * Sends the current message from the input field via WebSocket.
     */
    function sendMessage() {
        // Ensure input element exists and get its trimmed value
        if (!messageInput) {
            console.error("messageInput element not found.");
            return;
        }
        const message = messageInput.value.trim();

        // Check if message is not empty and WebSocket is open
        if (message && websocket && websocket.readyState === WebSocket.OPEN) {
            // console.log("Attempting to send message:", message); // Optional: Log sent message
            try {
                // Send the message over the WebSocket connection
                websocket.send(message);
                // console.log("Message sent. WebSocket readyState:", websocket.readyState); // Optional: Log state after sending
                messageInput.value = ""; // Clear the input field on successful send
            } catch (e) {
                console.error("Error sending message:", e);
                appendMessage(`<em>Failed to send message.</em>`, 'system-message');
            }
        } else if (!message) {
            console.warn("Cannot send empty message.");
        } else {
            console.warn("Cannot send message: WebSocket not connected or ready.");
            // Optional: appendMessage("<em>Cannot send message: Connection not ready.</em>", 'system-message');
        }
    }

    /**
     * Appends a new message HTML string to the messages display area.
     */
    function appendMessage(messageHtml, className = '') {
        // Ensure messages display element exists
        if (!messagesDiv) {
            console.error("messagesDiv element not found in appendMessage!");
            return;
        }

        // Create and configure the new message element
        const messageElement = document.createElement('p');
        messageElement.innerHTML = messageHtml; // Using innerHTML to allow bold, italics etc.
        if (className) {
            messageElement.classList.add(className);
        }

        // Add the message element to the display area
        messagesDiv.appendChild(messageElement);

        // Scroll the messages display to the bottom to show the latest message
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
        // console.log("Message appended.", messageHtml); // Optional: Log appended message
    }

    // --- Initialization ---

    // Update player info display based on initial template values
    updatePlayerInfoDisplay();

    // Connect to the WebSocket server if a valid session ID is found
    if (sessionId) {
        console.log("Session ID found. Attempting WebSocket connection.");
        connectWebSocket();
    } else {
        // This block should ideally not be reached if the initial redirect works
        console.error("Fatal: Session ID not found, but script continued execution unexpectedly.");
    }

    // --- Handle page closing ---
    // Close the WebSocket connection when the user leaves the page
    window.onbeforeunload = function () {
        console.log("Window onbeforeunload event triggered. Checking websocket state.");
        if (websocket && websocket.readyState === WebSocket.OPEN) {
            console.log("Closing websocket with code 1000 due to onbeforeunload.");
            websocket.close(1000, "Client leaving page");
        } else {
            console.log("Websocket not open or does not exist on onbeforeunload.");
        }
        // Returning a string from onbeforeunload can prompt the user,
        // but is often suppressed by browsers. Return undefined or nothing otherwise.
        // return "Are you sure you want to leave?"; // Example if confirmation needed
    };
});