from flask import render_template, url_for, flash, redirect, request
from app import app, db, bcrypt, socketio
from models import User, Friend, Message, Notification, FriendRequest
from flask_login import login_user, current_user, logout_user, login_required
from forms import RegistrationForm, LoginForm
from flask_socketio import send, emit, join_room, leave_room
from datetime import datetime

@app.route("/register", methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    form = RegistrationForm()
    if form.validate_on_submit():
        hashed_password = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
        user = User(username=form.username.data, email=form.email.data, password=hashed_password)
        db.session.add(user)
        db.session.commit()
        flash('Your account has been created! You are now able to log in', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', title='Register', form=form)

@app.route("/login", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and bcrypt.check_password_hash(user.password, form.password.data):
            login_user(user, remember=form.remember.data)
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('home'))
        else:
            flash('Login Unsuccessful. Please check email and password', 'danger')
    return render_template('login.html', title='Login', form=form)

@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for('home'))

@app.route("/home")
@login_required
def home():
    friends = Friend.query.filter_by(user_id=current_user.id).all()
    friend_requests = FriendRequest.query.filter_by(receiver_id=current_user.id, status='pending').all()
    notifications = Notification.query.filter_by(user_id=current_user.id).all()
    return render_template('home.html', friends=friends, friend_requests=friend_requests, notifications=notifications)

@app.route("/add_friend", methods=['POST'])
@login_required
def add_friend():
    friend_email = request.form.get('email')
    friend = User.query.filter_by(email=friend_email).first()
    if friend:
        new_friend_request = FriendRequest(sender_id=current_user.id, receiver_id=friend.id, status='pending')
        db.session.add(new_friend_request)
        db.session.commit()

        notification = Notification(user_id=friend.id, message=f"{current_user.username} sent you a friend request.", friend_request_id=new_friend_request.id)
        db.session.add(notification)
        db.session.commit()

        socketio.emit('new_notification', {'user_id': friend.id, 'message': f"{current_user.username} sent you a friend request.", 'friend_request_id': new_friend_request.id}, namespace='/')
        
        flash('Friend request sent successfully!', 'success')
    else:
        flash('User not found', 'danger')
    return redirect(url_for('home'))

@app.route("/accept_friend/<int:request_id>", methods=['POST'])
@login_required
def accept_friend(request_id):
    friend_request = FriendRequest.query.get_or_404(request_id)
    if friend_request.receiver_id == current_user.id:
        friend_request.status = 'accepted'
        new_friend = Friend(user_id=current_user.id, friend_id=friend_request.sender_id)
        new_friend_reverse = Friend(user_id=friend_request.sender_id, friend_id=current_user.id)
        db.session.add(new_friend)
        db.session.add(new_friend_reverse)
        db.session.commit()
        flash('Friend request accepted!', 'success')
    else:
        flash('You are not authorized to accept this friend request.', 'danger')
    return redirect(url_for('home'))

@app.route("/decline_friend/<int:request_id>", methods=['POST'])
@login_required
def decline_friend(request_id):
    friend_request = FriendRequest.query.get_or_404(request_id)
    if friend_request.receiver_id == current_user.id:
        friend_request.status = 'rejected'
        db.session.commit()
        flash('Friend request declined.', 'success')
    else:
        flash('You are not authorized to decline this friend request.', 'danger')
    return redirect(url_for('home'))

@app.route("/chat/<int:friend_id>", methods=['GET', 'POST'])
@login_required
def chat(friend_id):
    friend = User.query.get_or_404(friend_id)
    room = str(min(current_user.id, friend.id)) + '-' + str(max(current_user.id, friend.id))
    if request.method == 'POST':
        message_content = request.form.get('message')
        message = Message(content=message_content, author=current_user, recipient_id=friend_id)
        db.session.add(message)
        db.session.commit()
        socketio.emit('message', {'message': message_content, 'username': current_user.username, 'timestamp': datetime.utcnow().strftime('%H:%M:%S')}, room=room)
    messages_sent = Message.query.filter_by(user_id=current_user.id, recipient_id=friend_id).all()
    messages_received = Message.query.filter_by(user_id=friend_id, recipient_id=current_user.id).all()
    messages = sorted(messages_sent + messages_received, key=lambda x: x.date_posted)
    return render_template('chat.html', friend=friend, messages=messages, room=room)

@socketio.on('join')
def handle_join(data):
    username = data['username']
    room = data['room']
    join_room(room)
    send({'message': f'{username} has entered the room.', 'username': 'System'}, to=room)

@socketio.on('leave')
def handle_leave(data):
    username = data['username']
    room = data['room']
    leave_room(room)
    send({'message': f'{username} has left the room.', 'username': 'System'}, to=room)

@socketio.on('message')
def handle_message(data):
    room = data['room']
    data['timestamp'] = data.get('timestamp', datetime.utcnow().strftime('%H:%M:%S'))
    send({'message': data['message'], 'username': data['username'], 'timestamp': data['timestamp']}, to=room)
