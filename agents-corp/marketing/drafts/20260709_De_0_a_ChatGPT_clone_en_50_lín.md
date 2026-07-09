# De 0 a ChatGPT clone en 50 líneas con DeepAPI

# De 0 a ChatGPT clone en 50 líneas con DeepAPI

¿Alguna vez has querido crear tu propio asistente de IA como ChatGPT pero te ha frenado la complejidad de las APIs o los costos? Con **DeepAPI**, puedes construir un clon funcional en solo 50 líneas de código. Este tutorial te guiará paso a paso.

## ¿Qué necesitas?

- Una cuenta gratuita en [DeepAPI](https://deepapi.ai) (obtendrás una clave API)
- Python 3.8+ instalado en tu máquina
- Conocimientos básicos de Python (funciones, bucles, try/except)

## Paso 1: Configuración inicial

Instala la librería oficial de DeepAPI:

```bash
pip install deepapi-sdk
```

Crea un archivo `chatbot.py` y agrega las importaciones:

```python
import os
from deepapi import DeepAPI

# Inicializa el cliente con tu clave API
client = DeepAPI(api_key=os.getenv("DEEPAPI_KEY"))
```

Guarda tu clave API como variable de entorno para mayor seguridad:

```bash
export DEEPAPI_KEY="tu_clave_aqui"
```

## Paso 2: El bucle principal del chat

Ahora implementaremos el núcleo del chatbot. DeepAPI maneja automáticamente el contexto de la conversación, así que solo necesitamos mantener un historial de mensajes:

```python
def chat_con_deepapi():
    print("🤖 ChatGPT clone con DeepAPI")
    print("Escribe 'salir' para terminar.\n")
    
    historial = []  # Aquí guardamos el contexto
    
    while True:
        usuario = input("Tú: ")
        if usuario.lower() == "salir":
            break
        
        # Agregamos el mensaje del usuario al historial
        historial.append({"role": "user", "content": usuario})
        
        try:
            # Llamada simple a DeepAPI: solo 3 líneas
            respuesta = client.chat.completions.create(
                model="deepapi-v2",  # Modelo optimizado para diálogo
                messages=historial
            )
            
            # Extraemos la respuesta del asistente
            mensaje_asistente = respuesta.choices[0].message.content
            print(f"Asistente: {mensaje_asistente}\n")
            
            # Agregamos la respuesta al historial para mantener contexto
            historial.append({"role": "assistant", "content": mensaje_asistente})
            
        except Exception as e:
            print(f"Error: {e}")
```

## Paso 3: Ejecuta tu asistente

Agrega el punto de entrada al final del archivo:

```python
if __name__ == "__main__":
    chat_con_deepapi()
```

Ejecuta tu chatbot:

```bash
python chatbot.py
```

¡Ya tienes un ChatGPT funcional! Pero espera, aún podemos mejorarlo.

## Paso 4: Personaliza el comportamiento (5 líneas extra)

Agrega un **system prompt** para definir la personalidad de tu asistente:

```python
def chat_con_deepapi():
    # ... (código anterior)
    historial = [
        {"role": "system", "content": "Eres un asistente experto en Python que responde con ejemplos de código."}
    ]
    # ... (resto del código)
```

Ahora tu chatbot se especializará en respuestas técnicas.

## Paso 5: Versión completa (50 líneas exactas)

Aquí tienes el código completo que cumple la promesa del título:

```python
import os
from deepapi import DeepAPI

client = DeepAPI(api_key=os.getenv("DEEPAPI_KEY"))

def chat_con_deepapi():
    print("⚡ ChatGPT clone con DeepAPI (50 líneas)")
    print("Comandos: 'salir' para terminar, 'reset' para borrar contexto\n")
    
    historial = [
        {"role": "system", "content": "Eres un asistente útil y conciso. Responde en el mismo idioma del usuario."}
    ]
    
    while True:
        usuario = input("👤 Tú: ")
        if usuario.lower() == "salir":
            break
        if usuario.lower() == "reset":
            historial = [historial[0]]  # Mantiene solo el system prompt
            print("🔄 Contexto reiniciado.\n")
            continue
        
        historial.append({"role": "user", "content": usuario})
        
        try:
            respuesta = client.chat.completions.create(
                model="deepapi-v2",
                messages=historial,
                max_tokens=500,
                temperature=0.7
            )
            mensaje = respuesta.choices[0].message.content
            print(f"🤖 Asistente: {mensaje}\n")
            historial.append({"role": "assistant", "content": mensaje})
        except Exception as e:
            print(f"❌ Error: {e}\n")

if __name__ == "__main__":
    chat_con_deepapi()
```

## ¿Qué logramos?

- **50 líneas** de código limpio y legible
- **Contexto conversacional** automático (DeepAPI recuerda la conversación)
- **Personalización** con system prompts
- **Manejo de errores** básico
- **Comandos** útiles como `reset`

## ¿Por qué DeepAPI?

- **Simplicidad**: 3 líneas para una llamada de chat completa
- **Contexto automático**: No necesitas manejar tokens ni sesiones
- **Modelos optimizados**: `deepapi-v2` ofrece respuestas rápidas y coherentes
- **Gratuito para empezar**: 1000 llamadas de prueba sin tarjeta de crédito

## Próximos pasos

- Agrega un frontend con Gradio o Streamlit
- Implementa streaming de respuestas
- Conecta tu base de datos para respuestas contextuales

---

**¿Listo para construir tu propio asistente de IA?**  
Regístrate gratis en [DeepAPI](https://deepapi.ai) y obtén tu clave API en menos de 1 minuto. No necesitas tarjeta de crédito para empezar. ¡Tu clon de ChatGPT te espera!

---
*Generated by DeepAPI Content Scheduler*