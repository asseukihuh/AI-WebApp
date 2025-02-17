const textcontainer = document.getElementById('textresult');

let history = [];

async function SendMessage() {

    const textcontainer = document.getElementById('textresult');

    let prompt_text = document.getElementById("textarea1").value;
    if (prompt_text.trim() === "") return;
    // USER INPUT
        prompt_text = prompt_text.replace(/\n/g, "<br>");
        document.getElementById("innertext").innerHTML += `<b>You:</b> ${prompt_text}<br><br>`;
            
        document.getElementById("textarea1").value = "";

    //GET HISTORY USER

    history.push({ role: "user", content: prompt_text});

    // REQUEST TO OLLAMA
    try {
        let response = await fetch("http://localhost:11434/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                model: "mistral",
                messages: history, // GET HISTORY + PROMPT INSTEAD OF ONLY PROMPT TO GET MEMORY
                stream: false
            })
        });
        
        let data = await response.json();
        let ai_response = data.message?.content || "No response from AI";


        //GET HISTORY AI

        history.push({ role: "assistant", content: ai_response});
        
        //AI RESP
        ai_response = ai_response.replace(/\n/g, "<br>");
        document.getElementById("innertext").innerHTML += `<b>AI:</b> ${ai_response}<br><br>`;

    } catch (error) {
        console.error("Error fetching from Ollama:", error);
        document.getElementById("innertext").innerHTML += `<b>AI:</b> Error: Could not connect to Ollama.<br>`;
    }

}