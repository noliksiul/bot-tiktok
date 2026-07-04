<!DOCTYPE html >
<html lang = "es" >
<head >
 <meta charset = "UTF-8" >
   <title > Video de ejemplo < /title >
    <style >
    body {font-family: sans-serif
           text-align: center
           }
     # contador { font-size: 24px; margin: 20px; }
     # continuar { display: none; padding: 10px 20px; font-size: 18px; }
    </style >
</head >
<body >
  <h1 >🎥 Video de ejemplo < /h1 >
   <video id = "video" width = "320" controls autoplay >
       <source src = "https://www.w3schools.com/html/mov_bbb.mp4" type = "video/mp4" >
        Tu navegador no soporta video.
    </video >
    <div id = "contador" > 20 < /div>
    <button id = "continuar" >✅ Continuar < /button >

    <script src = "https://telegram.org/js/telegram-web-app.js" > </script >
    <script >
    let segundos = 20
    const contador = document.getElementById("contador")
     const boton = document.getElementById("continuar")

      const intervalo = setInterval(()= > {
           segundos--
            contador.textContent = segundos
           if (segundos <= 0) {
                clearInterval(intervalo)
                contador.textContent= "¡Tiempo terminado!"
              boton.style.display = "inline-block"
            }
           }, 1000);

        boton.addEventListener("click", ()= > {
            Telegram.WebApp.sendData("continuar")
        })
    </script >
</body >
</html >
ml >
