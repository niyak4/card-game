# У файлі backend/game_logic.py (або backend/models.py)

import random
from typing import List, Dict, Any, Optional

# Базові моделі для карт, гравців тощо (можна використовувати Pydantic для валідації)

class Card:
    def __init__(self, suit: str, rank: str):
        self.suit = suit
        self.rank = rank

    def __repr__(self):
        return f"{self.rank}{self.suit}"

    def to_dict(self, hidden=False):
        # Якщо карта прихована (наприклад, у руці іншого гравця),
        # ми можемо не показувати її масть і номінал
        if hidden:
            return {"suit": "hidden", "rank": "hidden"}
        return {"suit": self.suit, "rank": self.rank}

class Player:
    def __init__(self, player_id: str, name: str):
        self.player_id = player_id # Унікальний ID для гравця (може бути UUID або ID WebSocket з'єднання)
        self.name = name # Ім'я гравця
        self.hand: List[Card] = [] # Карти в руці гравця
        # Додатково: рахунок гравця, статус (активний, відключений, переміг)

    def to_dict(self, is_current_player=False):
        return {
            "player_id": self.player_id,
            "name": self.name,
            # Показуємо карти, якщо це поточний гравець, інакше лише кількість
            "hand": [card.to_dict() for card in self.hand] if is_current_player else len(self.hand),
            # Додаткові поля стану гравця
        }

class GameState:
    def __init__(self, game_id: str):
        self.game_id = game_id
        self.deck: List[Card] = [] # Колода карт
        self.discard_pile: List[Card] = [] # Скидання
        self.players: Dict[str, Player] = {} # Словник гравців: {player_id: Player_object}
        self.player_order: List[str] = [] # Порядок ходів гравців (список player_id)
        self.current_player_index: int = 0 # Індекс гравця, чий зараз хід
        self.table: List[Card] = [] # Карти на столі
        self.status: str = "waiting_for_players" # Статус гри (waiting_for_players, playing, finished)
        # Додаткові поля стану гри (наприклад, правила, лічильники)

    def add_player(self, player_id: str, name: str):
        if player_id not in self.players:
            player = Player(player_id, name)
            self.players[player_id] = player
            self.player_order.append(player_id)
            print(f"Гравець {name} ({player_id}) приєднався до гри {self.game_id}")
            return player
        return self.players[player_id] # Якщо гравець вже є

    def create_deck(self):
        suits = ["♥", "♦", "♣", "♠"] # Або інші позначення
        ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"] # Або інші номінали
        self.deck = [Card(s, r) for s in suits for r in ranks]
        random.shuffle(self.deck)
        print(f"Колоду створено та перемішано для гри {self.game_id}")

    def start_game(self):
        if self.status == "waiting_for_players" and len(self.players) >= 2: # Наприклад, потрібно хоча б 2 гравці
            self.create_deck()
            # Тут можна додати роздачу карт гравцям
            # Наприклад, для 5 карт на руку:
            for _ in range(5):
                for player_id in self.player_order:
                    if self.deck:
                        card = self.deck.pop(0)
                        self.players[player_id].hand.append(card)
            self.status = "playing"
            self.current_player_index = 0 # Хід першого гравця
            print(f"Гра {self.game_id} розпочалася. Хід гравця {self.get_current_player_id()}")

    def get_current_player_id(self) -> Optional[str]:
        if self.player_order and 0 <= self.current_player_index < len(self.player_order):
            return self.player_order[self.current_player_index]
        return None

    def next_turn(self):
        self.current_player_index = (self.current_player_index + 1) % len(self.player_order)
        print(f"Хід переходить до гравця {self.get_current_player_id()}")

    def draw_card_from_deck(self, player_id: str) -> Optional[Card]:
        if player_id not in self.players:
            return None
        if not self.deck:
            print("Колода порожня.")
            # Можна додати логіку перемішування скидання в колоду
            return None

        card = self.deck.pop(0)
        self.players[player_id].hand.append(card)
        print(f"Гравець {player_id} взяв карту з колоди.")
        return card

    def play_card_from_hand(self, player_id: str, card_suit: str, card_rank: str) -> Optional[Card]:
        if player_id not in self.players:
            print(f"Гравець {player_id} не знайдений.")
            return None
        if self.get_current_player_id() != player_id:
            print(f"Зараз не хід гравця {player_id}.")
            return None # Не його хід

        # Знайдіть карту в руці гравця
        card_to_play = None
        for card in self.players[player_id].hand:
            if card.suit == card_suit and card.rank == card_rank:
                card_to_play = card
                break

        if not card_to_play:
            print(f"Гравець {player_id} не має карти {card_rank}{card_suit} в руці.")
            return None # Карти немає в руці

        # TODO: Додати логіку перевірки, чи можна зіграти цю карту згідно правил гри

        # Видаляємо карту з руки
        self.players[player_id].hand.remove(card_to_play)
        # Додаємо карту на стіл або в скидання (залежить від гри)
        self.table.append(card_to_play) # Приклад: додаємо на стіл
        print(f"Гравець {player_id} зіграв карту {card_to_play}")

        # TODO: Додати логіку обробки зіграної карти (наприклад, зміна стану гри, активація ефекту)

        self.next_turn() # Переходимо до наступного ходу
        return card_to_play


    # Метод для отримання стану гри, який можна безпечно відправити клієнту (JSON-серіалізований)
    def get_state_for_player(self, requesting_player_id: str) -> Dict[str, Any]:
        # Цей метод формує стан гри так, щоб кожен гравець бачив свою руку повністю,
        # а руки інших гравців - лише кількість карт.
        players_state = {}
        for pid, player in self.players.items():
            players_state[pid] = player.to_dict(is_current_player=(pid == requesting_player_id))

        return {
            "game_id": self.game_id,
            "status": self.status,
            "current_player_id": self.get_current_player_id(),
            "deck_size": len(self.deck),
            "discard_size": len(self.discard_pile),
            "table": [card.to_dict() for card in self.table],
            "players": players_state,
            # Додаткова інформація про стан гри
        }