from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os
from datetime import datetime
import uuid

app = Flask(__name__)
app.secret_key = 'sua_chave_secreta_aqui'

# Configuração do banco de dados
DATABASE = 'bus_reservation.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    
    # Tabela de usuários
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            is_admin BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabela de ônibus
    conn.execute('''
        CREATE TABLE IF NOT EXISTS buses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate TEXT UNIQUE NOT NULL,
            seats INTEGER NOT NULL,
            bus_type TEXT NOT NULL CHECK(bus_type IN ('Convencional', 'Executivo', 'Leito')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabela de rotas
    conn.execute('''
        CREATE TABLE IF NOT EXISTS routes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            origin TEXT NOT NULL,
            destination TEXT NOT NULL,
            intermediate_stops TEXT,
            departure_time TEXT NOT NULL,
            arrival_time TEXT NOT NULL,
            price REAL NOT NULL,
            bus_id INTEGER NOT NULL,
            FOREIGN KEY (bus_id) REFERENCES buses (id)
        )
    ''')
    
    # Tabela de reservas
    conn.execute('''
        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            route_id INTEGER NOT NULL,
            user_id INTEGER,
            passenger_name TEXT NOT NULL,
            passenger_cpf TEXT NOT NULL,
            passenger_contact TEXT NOT NULL,
            seat_number INTEGER NOT NULL,
            ticket_number TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'confirmed',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (route_id) REFERENCES routes (id),
            FOREIGN KEY (user_id) REFERENCES users (id),
            UNIQUE(route_id, seat_number)
        )
    ''')
    
    # Criar usuário admin padrão
    admin_password = generate_password_hash('admin123')
    try:
        conn.execute('INSERT INTO users (username, password, is_admin) VALUES (?, ?, ?)',
                    ('admin', admin_password, 1))
    except sqlite3.IntegrityError:
        pass  # Usuário já existe
    
    conn.commit()
    conn.close()

# Inicializar banco de dados
init_db()

# Rotas principais
@app.route('/')
def index():
    conn = get_db_connection()
    routes = conn.execute('''
        SELECT r.*, b.plate, b.bus_type, b.seats
        FROM routes r
        JOIN buses b ON r.bus_id = b.id
        ORDER BY r.departure_time
    ''').fetchall()
    conn.close()
    return render_template('index.html', routes=routes)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['is_admin'] = user['is_admin']
            
            if user['is_admin']:
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('user_dashboard'))
        else:
            flash('Credenciais inválidas!', 'error')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        try:
            hashed_password = generate_password_hash(password)
            conn.execute('INSERT INTO users (username, password) VALUES (?, ?)',
                        (username, hashed_password))
            conn.commit()
            flash('Usuário criado com sucesso!', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Nome de usuário já existe!', 'error')
        finally:
            conn.close()
    
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# Rotas do usuário
@app.route('/user/dashboard')
def user_dashboard():
    if 'user_id' not in session or session.get('is_admin'):
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    conn = get_db_connection()
    reservations = conn.execute('''
        SELECT res.*, r.origin, r.destination, r.departure_time, r.arrival_time, r.price,
               b.plate, b.bus_type
        FROM reservations res
        JOIN routes r ON res.route_id = r.id
        JOIN buses b ON r.bus_id = b.id
        WHERE res.user_id = ?
        ORDER BY res.created_at DESC
    ''', (user_id,)).fetchall()
    conn.close()
    
    return render_template('user/dashboard.html', reservations=reservations)

@app.route('/book/<int:route_id>')
def book_route(route_id):
    conn = get_db_connection()
    route = conn.execute('''
        SELECT r.*, b.plate, b.bus_type, b.seats
        FROM routes r
        JOIN buses b ON r.bus_id = b.id
        WHERE r.id = ?
    ''', (route_id,)).fetchone()
    
    if not route:
        flash('Rota não encontrada!', 'error')
        return redirect(url_for('index'))
    
    # Buscar assentos ocupados
    occupied_seats = conn.execute(
        'SELECT seat_number FROM reservations WHERE route_id = ?',
        (route_id,)
    ).fetchall()
    occupied_seats = [seat['seat_number'] for seat in occupied_seats]
    
    conn.close()
    
    return render_template('user/book.html', route=route, occupied_seats=occupied_seats)

@app.route('/confirm_booking', methods=['POST'])
def confirm_booking():
    route_id = request.form['route_id']
    seat_number = request.form['seat_number']
    passenger_name = request.form['passenger_name']
    passenger_cpf = request.form['passenger_cpf']
    passenger_contact = request.form['passenger_contact']
    
    # Obter user_id da sessão (pode ser None se não logado)
    user_id = session.get('user_id')
    
    # Gerar número do bilhete
    ticket_number = str(uuid.uuid4())[:8].upper()
    
    conn = get_db_connection()
    try:
        conn.execute('''
            INSERT INTO reservations (route_id, user_id, passenger_name, passenger_cpf, 
                                    passenger_contact, seat_number, ticket_number)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (route_id, user_id, passenger_name, passenger_cpf, passenger_contact, seat_number, ticket_number))
        conn.commit()
        flash('Reserva realizada com sucesso!', 'success')
        return redirect(url_for('ticket', ticket_number=ticket_number))
    except sqlite3.IntegrityError:
        flash('Assento já reservado!', 'error')
        return redirect(url_for('book_route', route_id=route_id))
    finally:
        conn.close()

@app.route('/ticket/<ticket_number>')
def ticket(ticket_number):
    conn = get_db_connection()
    ticket_data = conn.execute('''
        SELECT res.*, r.origin, r.destination, r.departure_time, r.arrival_time, r.price,
               b.plate, b.bus_type
        FROM reservations res
        JOIN routes r ON res.route_id = r.id
        JOIN buses b ON r.bus_id = b.id
        WHERE res.ticket_number = ?
    ''', (ticket_number,)).fetchone()
    conn.close()
    
    if not ticket_data:
        flash('Bilhete não encontrado!', 'error')
        return redirect(url_for('index'))
    
    return render_template('user/ticket.html', ticket=ticket_data)

# Rotas do admin
@app.route('/admin/dashboard')
def admin_dashboard():
    if 'user_id' not in session or not session.get('is_admin'):
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    stats = {
        'total_buses': conn.execute('SELECT COUNT(*) as count FROM buses').fetchone()['count'],
        'total_routes': conn.execute('SELECT COUNT(*) as count FROM routes').fetchone()['count'],
        'total_reservations': conn.execute('SELECT COUNT(*) as count FROM reservations').fetchone()['count'],
    }
    conn.close()
    
    return render_template('admin/dashboard.html', stats=stats)

@app.route('/admin/buses')
def admin_buses():
    if 'user_id' not in session or not session.get('is_admin'):
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    buses = conn.execute('SELECT * FROM buses ORDER BY created_at DESC').fetchall()
    conn.close()
    
    return render_template('admin/buses.html', buses=buses)

@app.route('/admin/buses/add', methods=['POST'])
def add_bus():
    if 'user_id' not in session or not session.get('is_admin'):
        return redirect(url_for('login'))
    
    plate = request.form['plate']
    seats = request.form['seats']
    bus_type = request.form['bus_type']
    
    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO buses (plate, seats, bus_type) VALUES (?, ?, ?)',
                    (plate, seats, bus_type))
        conn.commit()
        flash('Ônibus adicionado com sucesso!', 'success')
    except sqlite3.IntegrityError:
        flash('Placa já existe!', 'error')
    finally:
        conn.close()
    
    return redirect(url_for('admin_buses'))

@app.route('/admin/routes')
def admin_routes():
    if 'user_id' not in session or not session.get('is_admin'):
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    routes = conn.execute('''
        SELECT r.*, b.plate, b.bus_type
        FROM routes r
        JOIN buses b ON r.bus_id = b.id
        ORDER BY r.departure_time
    ''').fetchall()
    buses = conn.execute('SELECT * FROM buses').fetchall()
    conn.close()
    
    return render_template('admin/routes.html', routes=routes, buses=buses)

@app.route('/admin/routes/add', methods=['POST'])
def add_route():
    if 'user_id' not in session or not session.get('is_admin'):
        return redirect(url_for('login'))
    
    origin = request.form['origin']
    destination = request.form['destination']
    intermediate_stops = request.form['intermediate_stops']
    departure_time = request.form['departure_time']
    arrival_time = request.form['arrival_time']
    price = request.form['price']
    bus_id = request.form['bus_id']
    
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO routes (origin, destination, intermediate_stops, departure_time, 
                          arrival_time, price, bus_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (origin, destination, intermediate_stops, departure_time, arrival_time, price, bus_id))
    conn.commit()
    conn.close()
    
    flash('Rota adicionada com sucesso!', 'success')
    return redirect(url_for('admin_routes'))

@app.route('/admin/reservations')
def admin_reservations():
    if 'user_id' not in session or not session.get('is_admin'):
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    reservations = conn.execute('''
        SELECT res.*, r.origin, r.destination, r.departure_time, r.price,
               b.plate, b.bus_type
        FROM reservations res
        JOIN routes r ON res.route_id = r.id
        JOIN buses b ON r.bus_id = b.id
        ORDER BY res.created_at DESC
    ''').fetchall()
    conn.close()
    
    return render_template('admin/reservations.html', reservations=reservations)

if __name__ == '__main__':
    app.run(debug=True,host="0.0.0.0",port=5000)