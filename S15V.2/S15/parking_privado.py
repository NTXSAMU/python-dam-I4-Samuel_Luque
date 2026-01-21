import random
import string
import threading
import time
import json
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import simpledialog, messagebox
from collections import deque

# ======================================================
# CONFIGURACIÓN GENERAL
# ======================================================

TIPOS_PARKING = {
    "SUBTERRANEO": 1.2,
    "AREA_PRIVADA": 1.1,
    "EXTERIOR": 0.9
}

TIPOS_VEHICULO = {
    "NORMAL": 1.0,
    "MINUSVALIDO": 0.7,
    "MOTO": 0.6,
    "ELECTRICO": 0.85
}

NUM_CARRILES_ENTRADA = 3
PORCENTAJE_MINUSVALIDOS = 0.20
PORCENTAJE_ELECTRICOS = 0.15
CAPACIDAD_MAXIMA = 56  # Total de plazas 

# COOLDOWNS REALISTAS (segundos)
ENTRADA_MIN, ENTRADA_MAX = 8, 15
SALIDA_MIN, SALIDA_MAX = 10, 20
TIEMPO_MINIMO_ESTANCIA = 120  # 2 minutos mínimo

# Patrones de tráfico realistas por hora
PATRONES_TRAFICO = {
    range(0, 6): 0.1,    # Madrugada: muy bajo
    range(6, 9): 1.5,    # Mañana: pico de entrada
    range(9, 12): 0.8,   # Media mañana: medio
    range(12, 14): 1.2,  # Mediodía: alto
    range(14, 17): 0.7,  # Tarde: medio-bajo
    range(17, 20): 1.4,  # Tarde-noche: pico de salida
    range(20, 24): 0.5   # Noche: bajo
}

# ======================================================
# MODELOS
# ======================================================

class Coche:
    def __init__(self, matricula, tipo):
        self.matricula = matricula
        self.tipo = tipo
        self.hora_entrada = None
        self.duracion_estimada = None  # En minutos

    def to_dict(self):
        """Convierte el coche a diccionario para JSON"""
        return {
            'matricula': self.matricula,
            'tipo': self.tipo,
            'hora_entrada': self.hora_entrada.isoformat() if self.hora_entrada else None,
            'duracion_estimada': self.duracion_estimada
        }
    
    @staticmethod
    def from_dict(data):
        """Crea un coche desde un diccionario JSON"""
        coche = Coche(data['matricula'], data['tipo'])
        if data['hora_entrada']:
            coche.hora_entrada = datetime.fromisoformat(data['hora_entrada'])
        coche.duracion_estimada = data['duracion_estimada']
        return coche

class Plaza:
    def __init__(self, pid, tipo_parking, exclusiva_minusvalido, es_electrica=False):
        self.id = pid
        self.tipo_parking = tipo_parking
        self.exclusiva_minusvalido = exclusiva_minusvalido
        self.es_electrica = es_electrica
        self.ocupada = False
        self.coche = None
        self.entrada = None

    def puede_entrar(self, coche):
        if self.ocupada:
            return False
        if self.exclusiva_minusvalido and coche.tipo != "MINUSVALIDO":
            return False
        if self.es_electrica and coche.tipo != "ELECTRICO":
            # Las plazas eléctricas prefieren coches eléctricos pero aceptan otros si quedan pocas plazas
            return False
        return True

    def puede_entrar_flexible(self, coche, ocupacion_alta):
        """Permite flexibilidad en plazas eléctricas cuando hay alta ocupación"""
        if self.ocupada:
            return False
        if self.exclusiva_minusvalido and coche.tipo != "MINUSVALIDO":
            return False
        if self.es_electrica and coche.tipo != "ELECTRICO" and not ocupacion_alta:
            return False
        return True

    def ocupar(self, coche):
        self.ocupada = True
        self.coche = coche
        self.entrada = datetime.now()
        coche.hora_entrada = self.entrada
        # Duración estimada realista
        coche.duracion_estimada = random.choices(
            [30, 60, 120, 180, 240, 480],  # minutos
            weights=[0.1, 0.3, 0.3, 0.15, 0.1, 0.05]
        )[0]

    def liberar(self):
        tiempo = datetime.now() - self.entrada
        coche = self.coche
        self.ocupada = False
        self.coche = None
        self.entrada = None
        return coche, tiempo

    def to_dict(self):
        """Convierte la plaza a diccionario para JSON"""
        return {
            'id': self.id,
            'tipo_parking': self.tipo_parking,
            'exclusiva_minusvalido': self.exclusiva_minusvalido,
            'es_electrica': self.es_electrica,
            'ocupada': self.ocupada,
            'coche': self.coche.to_dict() if self.coche else None,
            'entrada': self.entrada.isoformat() if self.entrada else None
        }
    
    @staticmethod
    def from_dict(data):
        """Crea una plaza desde un diccionario JSON"""
        plaza = Plaza(
            data['id'],
            data['tipo_parking'],
            data['exclusiva_minusvalido'],
            data['es_electrica']
        )
        plaza.ocupada = data['ocupada']
        if data['coche']:
            plaza.coche = Coche.from_dict(data['coche'])
        if data['entrada']:
            plaza.entrada = datetime.fromisoformat(data['entrada'])
        return plaza

# ======================================================
# GESTORES
# ======================================================

class GestorTarifas:
    BASE_POR_SEGUNDO = 1.5 / 20

    def calcular(self, tiempo, tipo_vehiculo, tipo_parking, reserva):
        segundos = tiempo.total_seconds()
        if segundos <= 30:
            return 0

        precio = (segundos - 30) * self.BASE_POR_SEGUNDO
        precio *= TIPOS_VEHICULO[tipo_vehiculo]
        precio *= TIPOS_PARKING[tipo_parking]

        hora = datetime.now().hour
        if 8 <= hora <= 10 or 18 <= hora <= 20:
            precio *= 1.3
        elif 22 <= hora or hora <= 6:
            precio *= 0.8

        if reserva:
            precio += 2.5

        return round(precio, 2)

class GestorPlazas:
    def __init__(self, plazas):
        self._plazas = plazas
        self._lock = threading.Lock()

    def asignar(self, coche):
        with self._lock:
            ocupacion = self.tasa_ocupacion()
            ocupacion_alta = ocupacion > 0.8
            
            # Primero intenta asignación estricta
            candidatas = [p for p in self._plazas if p.puede_entrar(coche)]
            
            # Si no hay y la ocupación es alta, permite flexibilidad en plazas eléctricas
            if not candidatas and ocupacion_alta:
                candidatas = [p for p in self._plazas if p.puede_entrar_flexible(coche, True)]
            
            if candidatas:
                # Preferir plazas del mismo tipo de parking que el coche
                if coche.tipo == "NORMAL":
                    preferidas = [p for p in candidatas if p.tipo_parking == "EXTERIOR"]
                    if preferidas:
                        candidatas = preferidas
                elif coche.tipo == "MOTO":
                    preferidas = [p for p in candidatas if p.tipo_parking == "AREA_PRIVADA"]
                    if preferidas:
                        candidatas = preferidas
                
                plaza = random.choice(candidatas)
                plaza.ocupar(coche)
                return plaza
        return None

    def liberar(self, pid):
        with self._lock:
            for plaza in self._plazas:
                if plaza.id == pid and plaza.ocupada:
                    return plaza.liberar(), plaza
        return None, None

    def ocupadas_ids(self):
        return [p.id for p in self._plazas if p.ocupada]

    def tasa_ocupacion(self):
        ocupadas = sum(1 for p in self._plazas if p.ocupada)
        return ocupadas / len(self._plazas)

    def estado(self):
        return self._plazas

class GestorCola:
    """Gestiona una cola de espera cuando el parking está lleno"""
    def __init__(self, max_cola=10):
        self._cola = deque(maxlen=max_cola)
        self._lock = threading.Lock()
    
    def agregar(self, coche):
        with self._lock:
            if len(self._cola) < self._cola.maxlen:
                self._cola.append(coche)
                return True
            return False
    
    def sacar(self):
        with self._lock:
            if self._cola:
                return self._cola.popleft()
            return None
    
    def tamaño(self):
        return len(self._cola)

# ======================================================
# PARKING (FACHADA)
# ======================================================

class Parking:
    def __init__(self):
        self._tarifas = GestorTarifas()
        self._plazas = GestorPlazas(self._crear_plazas())
        self._reservas = set()
        self._cola = GestorCola()
        self._estadisticas = {
            'total_entradas': 0,
            'total_salidas': 0,
            'rechazos': 0,
            'recaudacion_total': 0.0
        }
        self._lock_stats = threading.Lock()

    def _crear_plazas(self):
        plazas = []
        total = CAPACIDAD_MAXIMA
        num_minus = int(total * PORCENTAJE_MINUSVALIDOS)
        num_electric = int(total * PORCENTAJE_ELECTRICOS)

        todas = []
        for fila in "ABCDEFG":
            for col in range(1, 9):
                todas.append(f"{fila}{col}")

        minus_ids = set(random.sample(todas, num_minus))
        # Las eléctricas no pueden ser de minusválidos
        disponibles_electric = [p for p in todas if p not in minus_ids]
        electric_ids = set(random.sample(disponibles_electric, num_electric))

        for pid in todas:
            # Distribución realista de tipos de parking
            if pid[0] in ['A', 'B']:  # Primeras filas
                tipo = "AREA_PRIVADA"
            elif pid[0] in ['F', 'G']:  # Últimas filas
                tipo = "EXTERIOR"
            else:
                tipo = "SUBTERRANEO"
            
            plazas.append(
                Plaza(
                    pid,
                    tipo,
                    pid in minus_ids,
                    pid in electric_ids
                )
            )
        return plazas

    def _obtener_multiplicador_trafico(self):
        """Retorna el multiplicador de tráfico según la hora actual"""
        hora = datetime.now().hour
        for rango, mult in PATRONES_TRAFICO.items():
            if hora in rango:
                return mult
        return 1.0

    def entrada(self, reserva=False):
        # Distribución realista de tipos de vehículos
        tipo = random.choices(
            ["NORMAL", "MINUSVALIDO", "MOTO", "ELECTRICO"],
            weights=[0.5, 0.2, 0.15, 0.15]
        )[0]

        coche = Coche(self._generar_matricula(), tipo)
        plaza = self._plazas.asignar(coche)

        with self._lock_stats:
            if not plaza:
                # Intentar agregar a la cola
                if self._cola.agregar(coche):
                    self._estadisticas['rechazos'] += 1
                    return False, f"⏳ {coche.matricula} en cola de espera ({self._cola.tamaño()})"
                else:
                    self._estadisticas['rechazos'] += 1
                    return False, f"❌ {coche.matricula} rechazado - Parking lleno y cola completa"

            self._estadisticas['total_entradas'] += 1
            if reserva:
                self._reservas.add(coche.matricula)

        simbolo = "♿" if tipo == "MINUSVALIDO" else "🏍️" if tipo == "MOTO" else "⚡" if tipo == "ELECTRICO" else "🚗"
        return True, f"{simbolo} {coche.matricula} → {plaza.id} ({plaza.tipo_parking})"

    def salida(self, pid):
        resultado, plaza = self._plazas.liberar(pid)
        if not resultado:
            return False, "Plaza inválida o vacía"

        coche, tiempo = resultado
        
        # Verificar tiempo mínimo de estancia
        if tiempo.total_seconds() < TIEMPO_MINIMO_ESTANCIA:
            return False, f"⚠️ Estancia demasiado corta ({int(tiempo.total_seconds())}s)"

        reserva = coche.matricula in self._reservas
        self._reservas.discard(coche.matricula)

        precio = self._tarifas.calcular(
            tiempo, coche.tipo, plaza.tipo_parking, reserva
        )

        with self._lock_stats:
            self._estadisticas['total_salidas'] += 1
            self._estadisticas['recaudacion_total'] += precio

        minutos = int(tiempo.total_seconds() / 60)
        
        # Intentar meter un coche de la cola
        coche_cola = self._cola.sacar()
        if coche_cola:
            self.entrada()  # Intenta meter el siguiente de la cola
        
        return True, f"💰 {coche.matricula} → {precio}€ ({minutos}min)"

    def salida_aleatoria(self):
        ocupadas = self._plazas.ocupadas_ids()
        if not ocupadas:
            return False, "Sin coches"
        
        # Selección ponderada: coches que llevan más tiempo tienen más probabilidad de salir
        plazas_ocupadas = [p for p in self._plazas.estado() if p.ocupada]
        
        # Filtrar solo los que han estado el tiempo mínimo
        candidatas = []
        for plaza in plazas_ocupadas:
            tiempo_estancia = (datetime.now() - plaza.entrada).total_seconds()
            if tiempo_estancia >= TIEMPO_MINIMO_ESTANCIA:
                # Calcular probabilidad según tiempo estimado
                tiempo_transcurrido = (datetime.now() - plaza.coche.hora_entrada).total_seconds() / 60
                duracion_estimada = plaza.coche.duracion_estimada
                
                # Mayor probabilidad si ya pasó el tiempo estimado
                if tiempo_transcurrido >= duracion_estimada:
                    candidatas.extend([plaza] * 5)  # 5x más probable
                elif tiempo_transcurrido >= duracion_estimada * 0.8:
                    candidatas.extend([plaza] * 3)  # 3x más probable
                else:
                    candidatas.append(plaza)
        
        if not candidatas:
            return False, "Ningún coche listo para salir"
        
        plaza = random.choice(candidatas)
        return self.salida(plaza.id)

    def obtener_estado(self):
        return self._plazas.estado()

    def obtener_estadisticas(self):
        with self._lock_stats:
            return self._estadisticas.copy()

    def obtener_info_cola(self):
        return self._cola.tamaño()

    def _generar_matricula(self):
        return f"{random.randint(1000,9999)}{''.join(random.choices(string.ascii_uppercase,k=3))}"

    def guardar_estado(self, archivo='parking_estado.json'):
        """Guarda el estado completo del parking en un archivo JSON"""
        estado = {
            'timestamp': datetime.now().isoformat(),
            'plazas': [plaza.to_dict() for plaza in self._plazas.estado()],
            'reservas': list(self._reservas),
            'estadisticas': self._estadisticas.copy()
        }
        
        with open(archivo, 'w', encoding='utf-8') as f:
            json.dump(estado, f, indent=2, ensure_ascii=False)
        
        return True, f"Estado guardado en {archivo}"
    
    @staticmethod
    def cargar_estado(archivo='parking_estado.json'):
        """Carga el estado del parking desde un archivo JSON"""
        try:
            with open(archivo, 'r', encoding='utf-8') as f:
                estado = json.load(f)
            
            # Crear parking vacío
            parking = Parking()
            
            # Restaurar plazas
            plazas_restauradas = [Plaza.from_dict(p) for p in estado['plazas']]
            parking._plazas = GestorPlazas(plazas_restauradas)
            
            # Restaurar reservas
            parking._reservas = set(estado['reservas'])
            
            # Restaurar estadísticas
            parking._estadisticas = estado['estadisticas']
            
            return parking, f"Estado cargado desde {archivo} ({estado['timestamp']})"
        except FileNotFoundError:
            return None, f"Archivo {archivo} no encontrado"
        except Exception as e:
            return None, f"Error al cargar: {str(e)}"

# ======================================================
# INTERFAZ + AUTOMATIZACIÓN REALISTA
# ======================================================

class InterfazParking:
    def __init__(self, parking):
        self.parking = parking
        self.automatico = True
        self.velocidad = 1.0  # Factor de velocidad de simulación

        self.root = tk.Tk()
        self.root.title("🅿️ Sistema de Parking Inteligente")
        self.root.geometry("1400x800")
        self.root.configure(bg="#f0f0f0")

        # Frame superior con estadísticas
        frame_stats = tk.Frame(self.root, bg="#2c3e50", pady=10)
        frame_stats.pack(fill=tk.X)

        self.label_stats = tk.Label(
            frame_stats,
            text="Cargando estadísticas...",
            bg="#2c3e50",
            fg="white",
            font=("Arial", 11, "bold")
        )
        self.label_stats.pack()

        # Canvas para el parking
        self.canvas = tk.Canvas(self.root, bg="#ecf0f1")
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Frame de controles
        frame_controles = tk.Frame(self.root, bg="#34495e", pady=10)
        frame_controles.pack(fill=tk.X)

        tk.Button(
            frame_controles,
            text="🚗 Entrada Manual",
            command=self.entrada_manual,
            bg="#27ae60",
            fg="white",
            font=("Arial", 10, "bold"),
            padx=15,
            pady=5
        ).pack(side=tk.LEFT, padx=5)

        tk.Button(
            frame_controles,
            text="🚪 Salida Manual",
            command=self.salida_manual,
            bg="#e74c3c",
            fg="white",
            font=("Arial", 10, "bold"),
            padx=15,
            pady=5
        ).pack(side=tk.LEFT, padx=5)

        tk.Button(
            frame_controles,
            text="⏸️ Pausar/Reanudar",
            command=self.toggle_auto,
            bg="#9b59b6",
            fg="white",
            font=("Arial", 10, "bold"),
            padx=15,
            pady=5
        ).pack(side=tk.LEFT, padx=5)

        tk.Button(
            frame_controles,
            text="📊 Estadísticas",
            command=self.mostrar_estadisticas,
            bg="#3498db",
            fg="white",
            font=("Arial", 10, "bold"),
            padx=15,
            pady=5
        ).pack(side=tk.LEFT, padx=5)

        tk.Button(
            frame_controles,
            text="💾 Guardar Estado",
            command=self.guardar_estado_json,
            bg="#16a085",
            fg="white",
            font=("Arial", 10, "bold"),
            padx=15,
            pady=5
        ).pack(side=tk.LEFT, padx=5)

        tk.Button(
            frame_controles,
            text="📂 Cargar Estado",
            command=self.cargar_estado_json,
            bg="#d35400",
            fg="white",
            font=("Arial", 10, "bold"),
            padx=15,
            pady=5
        ).pack(side=tk.LEFT, padx=5)

        # Frame de velocidad
        tk.Label(
            frame_controles,
            text="Velocidad:",
            bg="#34495e",
            fg="white",
            font=("Arial", 9)
        ).pack(side=tk.LEFT, padx=(20, 5))

        self.speed_var = tk.StringVar(value="1x")
        speeds = ["0.5x", "1x", "2x", "5x"]
        speed_menu = tk.OptionMenu(frame_controles, self.speed_var, *speeds, command=self.cambiar_velocidad)
        speed_menu.config(bg="#16a085", fg="white", font=("Arial", 9))
        speed_menu.pack(side=tk.LEFT)

        # Iniciar hilos de simulación
        for _ in range(NUM_CARRILES_ENTRADA):
            threading.Thread(target=self.carril_entrada, daemon=True).start()

        threading.Thread(target=self.bucle_salida, daemon=True).start()
        threading.Thread(target=self.actualizar_interfaz, daemon=True).start()

        self.dibujar()

    def cambiar_velocidad(self, valor):
        self.velocidad = float(valor.replace('x', ''))

    def carril_entrada(self):
        while True:
            if self.automatico:
                mult = self.parking._obtener_multiplicador_trafico()
                # Ajustar probabilidad de entrada según tráfico y ocupación
                ocupacion = self.parking._plazas.tasa_ocupacion()
                
                if ocupacion < 0.9:  # Solo intentar entradas si no está casi lleno
                    probabilidad = mult * (1 - ocupacion * 0.5)
                    if random.random() < probabilidad:
                        self.parking.entrada(reserva=random.random() < 0.15)
            
            tiempo_espera = random.uniform(ENTRADA_MIN, ENTRADA_MAX) / self.velocidad
            time.sleep(tiempo_espera)

    def bucle_salida(self):
        while True:
            if self.automatico:
                self.parking.salida_aleatoria()
            
            tiempo_espera = random.uniform(SALIDA_MIN, SALIDA_MAX) / self.velocidad
            time.sleep(tiempo_espera)

    def actualizar_interfaz(self):
        """Actualiza la interfaz periódicamente"""
        while True:
            self.root.after(0, self.dibujar)
            time.sleep(1 / self.velocidad)

    def dibujar(self):
        self.canvas.delete("all")
        
        # Actualizar estadísticas
        stats = self.parking.obtener_estadisticas()
        ocupacion = self.parking._plazas.tasa_ocupacion()
        cola = self.parking.obtener_info_cola()
        
        stats_text = (
            f"📊 Ocupación: {ocupacion*100:.1f}% | "
            f"🚗 Entradas: {stats['total_entradas']} | "
            f"🚪 Salidas: {stats['total_salidas']} | "
            f"❌ Rechazos: {stats['rechazos']} | "
            f"💰 Recaudación: {stats['recaudacion_total']:.2f}€ | "
            f"⏳ Cola: {cola}"
        )
        self.label_stats.config(text=stats_text)
        
        # Leyenda
        y_leyenda = 10
        self.canvas.create_text(10, y_leyenda, text="Leyenda:", anchor="w", font=("Arial", 9, "bold"))
        self.canvas.create_rectangle(80, y_leyenda-8, 100, y_leyenda+8, fill="#ff4757")
        self.canvas.create_text(105, y_leyenda, text="Ocupada", anchor="w", font=("Arial", 8))
        self.canvas.create_rectangle(170, y_leyenda-8, 190, y_leyenda+8, fill="#5bc0de")
        self.canvas.create_text(195, y_leyenda, text="Minusválido", anchor="w", font=("Arial", 8))
        self.canvas.create_rectangle(280, y_leyenda-8, 300, y_leyenda+8, fill="#ffd700")
        self.canvas.create_text(305, y_leyenda, text="Eléctrica", anchor="w", font=("Arial", 8))
        self.canvas.create_rectangle(380, y_leyenda-8, 400, y_leyenda+8, fill="#2ecc71")
        self.canvas.create_text(405, y_leyenda, text="Libre", anchor="w", font=("Arial", 8))
        
        # Dibujar plazas
        x, y = 50, 50
        
        for plaza in self.parking.obtener_estado():
            # Determinar color
            if plaza.ocupada:
                color = "#ff4757"
                borde = "#c23616"
            elif plaza.exclusiva_minusvalido:
                color = "#5bc0de"
                borde = "#3498db"
            elif plaza.es_electrica:
                color = "#ffd700"
                borde = "#f39c12"
            else:
                color = "#2ecc71"
                borde = "#27ae60"

            # Dibujar plaza
            self.canvas.create_rectangle(
                x, y, x+120, y+65,
                fill=color,
                outline=borde,
                width=2
            )
            
            # ID de plaza
            self.canvas.create_text(
                x+60, y+10,
                text=plaza.id,
                font=("Arial", 11, "bold"),
                fill="#2c3e50"
            )
            
            # Tipo de parking
            tipo_abrev = {
                "SUBTERRANEO": "🌙 SUB",
                "AREA_PRIVADA": "🏢 PRIV",
                "EXTERIOR": "🌤️ EXT"
            }
            self.canvas.create_text(
                x+60, y+25,
                text=tipo_abrev.get(plaza.tipo_parking, plaza.tipo_parking),
                font=("Arial", 7),
                fill="#34495e"
            )
            
            # Matrícula o estado
            if plaza.coche:
                simbolo = "♿" if plaza.coche.tipo == "MINUSVALIDO" else "🏍️" if plaza.coche.tipo == "MOTO" else "⚡" if plaza.coche.tipo == "ELECTRICO" else "🚗"
                self.canvas.create_text(
                    x+60, y+40,
                    text=f"{simbolo} {plaza.coche.matricula}",
                    font=("Arial", 9)
                )
                
                # Tiempo de estancia
                tiempo = (datetime.now() - plaza.entrada).total_seconds() / 60
                self.canvas.create_text(
                    x+60, y+55,
                    text=f"{int(tiempo)}min",
                    font=("Arial", 8),
                    fill="#555"
                )
            else:
                tipo_texto = "MINUS" if plaza.exclusiva_minusvalido else "⚡ELEC" if plaza.es_electrica else "LIBRE"
                self.canvas.create_text(
                    x+60, y+45,
                    text=tipo_texto,
                    font=("Arial", 9),
                    fill="#555"
                )

            x += 130
            if x > 1200:
                x = 50
                y += 80

    def entrada_manual(self):
        self.parking.entrada(reserva=messagebox.askyesno("Reserva", "¿Tiene reserva?"))
        self.dibujar()

    def salida_manual(self):
        pid = simpledialog.askstring("Salida", "ID de plaza (ej: A1):")
        if pid:
            exito, msg = self.parking.salida(pid.upper())
            messagebox.showinfo("Resultado", msg)
            self.dibujar()

    def toggle_auto(self):
        self.automatico = not self.automatico
        estado = "▶️ ACTIVO" if self.automatico else "⏸️ PAUSADO"
        messagebox.showinfo("Estado", f"Modo automático: {estado}")

    def mostrar_estadisticas(self):
        stats = self.parking.obtener_estadisticas()
        ocupacion = self.parking._plazas.tasa_ocupacion()
        
        mensaje = f"""
📊 ESTADÍSTICAS DEL PARKING
{'='*40}

🚗 Total Entradas: {stats['total_entradas']}
🚪 Total Salidas: {stats['total_salidas']}
❌ Rechazos: {stats['rechazos']}
💰 Recaudación Total: {stats['recaudacion_total']:.2f}€

📈 Ocupación Actual: {ocupacion*100:.1f}%
⏳ Cola de Espera: {self.parking.obtener_info_cola()} vehículos

💵 Media por vehículo: {stats['recaudacion_total']/max(stats['total_salidas'],1):.2f}€
        """
        
        messagebox.showinfo("Estadísticas Detalladas", mensaje)

    def guardar_estado_json(self):
        """Guarda el estado actual del parking en JSON"""
        # Pausar modo automático temporalmente
        automatico_prev = self.automatico
        self.automatico = False
        time.sleep(0.5)  # Esperar a que terminen operaciones en curso
        
        exito, mensaje = self.parking.guardar_estado()
        
        if exito:
            messagebox.showinfo("💾 Guardado Exitoso", mensaje)
        else:
            messagebox.showerror("❌ Error", mensaje)
        
        # Restaurar modo automático
        self.automatico = automatico_prev

    def cargar_estado_json(self):
        """Carga el estado del parking desde JSON"""
        # Pausar modo automático
        automatico_prev = self.automatico
        self.automatico = False
        time.sleep(0.5)
        
        respuesta = messagebox.askyesno(
            "📂 Cargar Estado",
            "¿Desea cargar el estado guardado?\nSe perderá el estado actual."
        )
        
        if respuesta:
            parking_nuevo, mensaje = Parking.cargar_estado()
            
            if parking_nuevo:
                self.parking = parking_nuevo
                messagebox.showinfo("✅ Carga Exitosa", mensaje)
                self.dibujar()
            else:
                messagebox.showerror("❌ Error", mensaje)
        
        # Restaurar modo automático
        self.automatico = automatico_prev

    def iniciar(self):
        self.root.mainloop()

# ======================================================
# MAIN
# ======================================================

if __name__ == "__main__":
    parking = Parking()
    InterfazParking(parking).iniciar()