# Web Platform for Board Games

## Description

Web platform for board games. The main idea is to develop a ready-made base for implementing any board game that can be played online with friends, even without website deployment (use ngrok instead).

## TODO:

### Backend:
- [x] Base websockets functionality.
- [x] Implement the assignment of the user ID and session ID.
- [x] Implement user registration functionality.
- [x] Implement simple txt database.
    - [x] Chat state.
    - [x] Active sessions.
    - [x] Registered users.
- [ ] Add API endpoints to allow an admin to manage the game.
    - [ ] Kick specific user.
    - [ ] Clear chat history.
    - [ ] Restart the game without a server reboot.
    - [ ]

### Design:
- [ ] Develop User Interface.

### Frontend:
- [ ] Implement basic User Interface.

### Security:
- [ ] Implement cookies to avoid user session compromise.
- [x] Allow only one active session per user.
    - [x] Only one user can be logged-in using the same credentials.
    - [x] Only one tab can be used with the same session id.
- [ ] ---

## Contribution

Create virtual environment:

```bash
python -m venv venv
```

Move to backend dir:

```bash
cd backend
```

Activate virtual environment:

```bash
venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run server:

```bash
uvicorn main:app --reload
```