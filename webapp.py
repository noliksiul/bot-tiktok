import os
import asyncpg
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)
DATABASE_URL = os.getenv("DATABASE_URL")


async def get_db():
    return await asyncpg.connect(DATABASE_URL)


@app.route("/")
def index():
    telegram_id = request.args.get("id")
    html = f"""
    <html>
    <head>
      <script>
        let segundos = 60;
        function contador() {{
          if (segundos > 0) {{
            document.getElementById("timer").innerHTML = segundos + "s";
            segundos--;
            setTimeout(contador, 1000);
          }} else {{
            document.getElementById("acciones").style.display = "block";
          }}
        }}
        window.onload = contador;

        async function enviarAccion(tipo) {{
          const res = await fetch("/accion", {{
            method: "POST",
            headers: {{"Content-Type":"application/json"}},
            body: JSON.stringify({{telegram_id: {telegram_id}, tipo: tipo}})
          }});
          const data = await res.json();
          alert(data.mensaje);
        }}
      </script>
    </head>
    <body>
      <h1>🎥 Video TikTok</h1>
      <p id="timer">60s</p>
      <div id="acciones" style="display:none;">
        <button onclick="enviarAccion('solo_vio')">Solo miré</button>
        <button onclick="enviarAccion('like_share')">Like + Share</button>
      </div>
    </body>
    </html>
    """
    return render_template_string(html)


@app.route("/accion", methods=["POST"])
async def accion():
    data = request.get_json()
    telegram_id = data.get("telegram_id")
    tipo = data.get("tipo")

    conn = await get_db()
    user = await conn.fetchrow("SELECT id FROM users WHERE telegram_id=$1", telegram_id)
    if not user:
        await conn.close()
        return jsonify({"mensaje": "⚠️ Usuario no registrado"})

    puntos = 0.25 if tipo == "solo_vio" else 0
    descripcion = "Vió un video" if tipo == "solo_vio" else "Like + Share pendiente"

    # Registrar movimiento
    await conn.execute(
        "INSERT INTO movimientos (user_id, descripcion, puntos) VALUES ($1, $2, $3)",
        user["id"], descripcion, puntos
    )

    # Si fue "solo_vio", sumar puntos al usuario
    if tipo == "solo_vio":
        await conn.execute("UPDATE users SET puntos = puntos + $1 WHERE id=$2", puntos, user["id"])

    await conn.close()
    return jsonify({"mensaje": "✅ Acción registrada"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
