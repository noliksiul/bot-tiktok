from flask import Flask, render_template_string

app = Flask(__name__)


@app.route("/")
def index():
    html = """
    <html>
    <head>
      <script>
        let segundos = 60;
        function contador() {
          if (segundos > 0) {
            document.getElementById("timer").innerHTML = segundos + "s";
            segundos--;
            setTimeout(contador, 1000);
          } else {
            document.getElementById("acciones").style.display = "block";
          }
        }
        window.onload = contador;
      </script>
    </head>
    <body>
      <h1>🎥 Video TikTok</h1>
      <p id="timer">60s</p>
      <div id="acciones" style="display:none;">
        <button onclick="alert('Ganaste 0.25 puntos')">Solo miré</button>
        <button onclick="alert('Solicitud enviada al dueño')">Like + Share</button>
      </div>
    </body>
    </html>
    """
    return render_template_string(html)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
