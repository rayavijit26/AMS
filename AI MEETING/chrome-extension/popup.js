// --- THIS ENTIRE FILE IS REPLACED ---

// Get DOM elements
const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");
const statusBox = document.getElementById("status");
const summarySection = document.getElementById("summarySection");
const summaryContent = document.getElementById("summaryContent");
const transcriptSection = document.getElementById("transcriptSection");
const transcriptContent = document.getElementById("transcriptContent");
const chatSection = document.getElementById("chatSection");
const chatInput = document.getElementById("chatInput");
const sendBtn = document.getElementById("sendBtn");
const chatMessages = document.getElementById("chatMessages");


// --- Utility Functions ---
function updateStatus(state, mainText, detailText = "") {
    statusBox.className = `status ${state}`;
    statusBox.querySelector(".status-text").textContent = mainText;
    statusBox.querySelector(".status-detail").textContent = detailText;

    if (state === 'recording') {
        startBtn.disabled = true;
        stopBtn.disabled = false;
    } else if (state === 'processing') {
        startBtn.disabled = true;
        stopBtn.disabled = true;
    } else { // idle or error
        startBtn.disabled = false;
        stopBtn.disabled = true;
    }
}

function showSummary(summary, transcript) {
    summarySection.style.display = "block";
    summaryContent.textContent = summary;
    
    transcriptSection.style.display = "block";
    transcriptContent.textContent = transcript;
    
    chatSection.style.display = "block"; // Show chat section

    updateStatus("idle", "Summary Received", "Ready for new recording.");
}

// --- Event Listeners for Buttons ---

startBtn.addEventListener("click", () => {
    console.log("Sending 'startRecording' message to background.");
    // Send "start" command to the service worker
    chrome.runtime.sendMessage({ type: "startRecording" });
});

stopBtn.addEventListener("click", () => {
    console.log("Sending 'stopRecording' message to background.");
    // Send "stop" command to the service worker
    chrome.runtime.sendMessage({ type: "stopRecording" });
});

// --- Listen for messages FROM the background script ---
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.type === 'statusUpdate') {
        console.log("Popup received status:", request.message);
        const state = request.isRecording ? 'recording' : (request.message.toLowerCase().includes('processing') ? 'processing' : 'idle');
        
        if (request.message.toLowerCase().includes('error')) {
             updateStatus('idle', 'Error', request.message);
        } else {
             updateStatus(state, request.isRecording ? 'Recording...' : 'Idle', request.message);
        }

    } else if (request.type === 'summaryComplete') { 
        console.log("Popup received summary and transcript.");
        showSummary(request.summary, request.transcript); // Pass both
    }
});

// --- On Popup Load: Get current status ---
document.addEventListener('DOMContentLoaded', () => {
    // Ask the background script for its current state
    chrome.runtime.sendMessage({ type: "getRecordingState" });
    
    // --- Chat Functionality ---
    sendBtn.addEventListener("click", handleChatSend);
    chatInput.addEventListener("keyup", (e) => {
        if (e.key === "Enter") {
            handleChatSend();
        }
    });
});

async function handleChatSend() {
    const question = chatInput.value;
    if (!question) return;

    appendChatMessage("User:", question);
    chatInput.value = "";
    sendBtn.disabled = true;

    try {
        const response = await fetch("http://127.0.0.1:5000/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question: question })
        });
        
        if (!response.ok) {
            throw new Error("Server error");
        }
        
        const data = await response.json();
        appendChatMessage("AI:", data.answer);

    } catch (error) {
        console.error("Chat error:", error);
        appendChatMessage("Error:", "Could not get a response from the server.");
    } finally {
        sendBtn.disabled = false;
    }
}

function appendChatMessage(sender, message) {
    const messageEl = document.createElement("div");
    messageEl.innerHTML = `<strong>${sender}</strong><br>${message}`;
    chatMessages.appendChild(messageEl);
    chatMessages.scrollTop = chatMessages.scrollHeight; // Auto-scroll
}