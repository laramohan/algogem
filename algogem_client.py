#!/usr/bin/env python3
"""ALGOGEM Client - Connect your bot to the game server.

This file contains the networking client, game logger, data types, and the
AlgogemBot base class. You should NOT need to edit this file.

YOUR BOT goes in algogem_bot.py - edit that file instead!

Usage:
    python algogem_client.py --server <ip> --token <token> --mode practice
"""

import asyncio
import csv
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# === Data Types ===


class GemType(Enum):
    GREEN = "green"
    BLUE = "blue"
    PINK = "pink"
    PURPLE = "purple"
    ORANGE = "orange"


@dataclass
class AuctionCard:
    """An auction card."""

    auction_type: str  # "treasure_1", "treasure_2", "loan", "invest"
    value: int | None = None  # Loan amount or investment return (None for treasure)
    available_gems: list[str] | None = None  # Gems to win (None for loans/investments)


@dataclass
class MissionCard:
    """A mission card."""

    mission_id: int
    required_gems: list[str]  # List of gem type strings
    reward: int
    mission_type: str  # "specific", "n_same", "n_different", "two_pairs"
    wildcard_count: int


# === Parser functions (internal) ===


def _parse_gem(data: dict[str, Any]) -> GemType:
    return GemType(data["gem_type"])


def _parse_auction_card(data: dict[str, Any]) -> AuctionCard:
    available_gems_data = data.get("available_gems")
    return AuctionCard(
        auction_type=data["auction_type"],
        value=data.get("value"),
        available_gems=available_gems_data if available_gems_data is not None else None,
    )


def _parse_mission_card(data: dict[str, Any]) -> MissionCard:
    return MissionCard(
        mission_id=data["mission_id"],
        required_gems=data.get("required_gems", []),
        reward=data["reward"],
        mission_type=data.get("mission_type", "specific"),
        wildcard_count=data.get("wildcard_count", 0),
    )


# === Game Logger ===


class GameLogger:
    """Logs game events to per-game folders with transcripts and CSV data.

    Output structure:
        game_data/
        └── practice_20240115_143022/
            ├── summary.csv           # One row per game (session summary)
            ├── game_001_112233/
            │   ├── transcript.txt    # Human-readable game log
            │   ├── auctions.csv      # Auction data for this game
            │   ├── reveals.csv       # Card reveals for this game
            │   └── missions.csv      # Mission completions for this game
            ├── game_002_112345/
            │   └── ...
    """

    def __init__(self, data_dir: str = "./game_data", mode: str = "practice"):
        self.data_dir = Path(data_dir)
        self.mode = mode
        self._session_dir: Path | None = None
        self._game_dir: Path | None = None
        self._game_num: int = 0
        self._game_id: str = ""
        self._player_id: int = 0
        self._auction_num: int = 0
        self._bot_level: int | None = None
        self._started_at: str = ""
        self._last_available_gems: list[GemType] = []
        self._starting_hand: list[GemType] = []
        self._starting_coins: int = 0
        self.not_revealed = list(GemType)

        # Session-level summary CSV
        self._summary_file: Any = None
        self._summary_writer: Any = None

        # Per-game files
        self._auctions_file: Any = None
        self._auctions_writer: Any = None
        self._reveals_file: Any = None
        self._reveals_writer: Any = None
        self._missions_file: Any = None
        self._missions_writer: Any = None

        # Transcript buffer
        self._transcript: list[str] = []

    def _ensure_session_dir(self) -> Path:
        if self._session_dir is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._session_dir = self.data_dir / f"{self.mode}_{timestamp}"
            self._session_dir.mkdir(parents=True, exist_ok=True)
            self._init_summary_file()
        return self._session_dir

    def _init_summary_file(self) -> None:
        assert self._session_dir is not None
        self._summary_file = open(self._session_dir / "summary.csv", "w", newline="")
        self._summary_writer = csv.writer(self._summary_file)
        self._summary_writer.writerow(
            [
                "game_num",
                "game_id",
                "mode",
                "bot_level",
                "my_player_id",
                "started_at",
                "my_score",
                "winner",
                "i_won",
                "score_p0",
                "score_p1",
                "score_p2",
                "score_p3",
            ]
        )

    def _init_game_files(self) -> None:
        assert self._game_dir is not None

        self._auctions_file = open(self._game_dir / "auctions.csv", "w", newline="")
        self._auctions_writer = csv.writer(self._auctions_file)
        self._auctions_writer.writerow(
            [
                "auction_num",
                "auction_type",
                "auction_value",
                "gem1",
                "gem2",
                "bid_p0",
                "bid_p1",
                "bid_p2",
                "bid_p3",
                "winner",
                "winning_bid",
                "i_won",
            ]
        )

        self._reveals_file = open(self._game_dir / "reveals.csv", "w", newline="")
        self._reveals_writer = csv.writer(self._reveals_file)
        self._reveals_writer.writerow(["auction_num", "player_id", "gem_type", "is_me"])

        self._missions_file = open(self._game_dir / "missions.csv", "w", newline="")
        self._missions_writer = csv.writer(self._missions_file)
        self._missions_writer.writerow(
            ["auction_num", "player_id", "mission_id", "reward", "gems_used", "is_me"]
        )

    def _close_game_files(self) -> None:
        for f in [self._auctions_file, self._reveals_file, self._missions_file]:
            if f:
                try:
                    f.close()
                except Exception:
                    pass
        self._auctions_file = None
        self._reveals_file = None
        self._missions_file = None

    def _write_transcript(self) -> None:
        if self._game_dir and self._transcript:
            with open(self._game_dir / "transcript.txt", "w") as f:
                f.write("\n".join(self._transcript))

    @property
    def session_dir(self) -> Path | None:
        """Directory this session's logs are written to (None until a game starts)."""
        return self._session_dir

    def _log(self, message: str) -> None:
        """Add a line to the transcript."""
        self._transcript.append(message)

    def _me(self, player_id: int) -> str:
        """Return ' (ME)' if this is our player."""
        return " (ME)" if player_id == self._player_id else ""

    def set_bot_level(self, level: int) -> None:
        self._bot_level = level

    def start_game(
        self,
        player_id: int,
        hand: list[GemType],
        starting_coins: int,
        available_gems: list[GemType],
        available_missions: list[MissionCard],
        value_chart: dict[int, int],
    ) -> None:
        self._ensure_session_dir()
        self._close_game_files()

        # Create game folder
        self._game_num += 1
        self._game_id = datetime.now().strftime("%H%M%S")
        self._game_dir = (
            self._session_dir / f"game_{self._game_num:03d}_{self._game_id}"
        )
        self._game_dir.mkdir(parents=True, exist_ok=True)

        self._player_id = player_id
        self._auction_num = 0
        self._started_at = datetime.now().isoformat()
        self._last_available_gems = list(available_gems)
        self._starting_hand = list(hand)
        self._starting_coins = starting_coins

        # Initialize per-game files
        self._init_game_files()

        # Start transcript
        self._transcript = []
        self._log("=" * 60)
        self._log(f"GAME {self._game_num} - {self._started_at}")
        self._log("=" * 60)
        self._log("")
        self._log(f"Mode: {self.mode}")
        if self._bot_level:
            self._log(f"Bot Level: {self._bot_level}")
        self._log(f"I am Player {player_id}")
        self._log(f"Starting coins: {starting_coins}")
        self._log(f"Value chart: {value_chart}  # count_in_display -> coin_value")
        self._log("")
        self._log("My starting hand:")
        for i, card in enumerate(hand):
            self._log(f"  [{i}] {card.value}")
        self._log("")
        self._log("Available gems:")
        for gem in available_gems:
            self._log(f"  - {gem.value}")
        self._log("")
        self._log(f"Available missions: {len(available_missions)}")
        for m in available_missions:
            gems_str = (
                ", ".join(m.required_gems) if m.required_gems else f"{m.mission_type}"
            )
            self._log(f"  - Mission {m.mission_id}: {gems_str} -> {m.reward} coins")
        self._log("")
        self._log("-" * 60)
        self._log("AUCTIONS")
        self._log("-" * 60)

    def set_available_gems(self, gems: list[GemType]) -> None:
        self._last_available_gems = list(gems)

    def log_auction_result(
        self,
        auction_card: AuctionCard,
        winner: int,
        winning_bid: int,
        all_bids: dict[int, int],
        gems_won: list[GemType],
    ) -> None:
        self._auction_num += 1

        gem1 = (
            self._last_available_gems[0].value
            if len(self._last_available_gems) > 0
            else ""
        )
        gem2 = (
            self._last_available_gems[1].value
            if len(self._last_available_gems) > 1
            else ""
        )

        # CSV
        if self._auctions_writer:
            self._auctions_writer.writerow(
                [
                    self._auction_num,
                    auction_card.auction_type,
                    auction_card.value,
                    gem1,
                    gem2,
                    all_bids.get(0, 0),
                    all_bids.get(1, 0),
                    all_bids.get(2, 0),
                    all_bids.get(3, 0),
                    winner,
                    winning_bid,
                    1 if winner == self._player_id else 0,
                ]
            )
            self._auctions_file.flush()

        # Transcript
        self._log("")
        gems_str = (
            " + ".join(g.value for g in self._last_available_gems)
            if self._last_available_gems
            else "N/A"
        )
        self._log(f"Auction #{self._auction_num}: {auction_card.auction_type.upper()}")
        if auction_card.value:
            self._log(f"  Value: {auction_card.value} coins")
        self._log(f"  Available gems: [{gems_str}]")
        self._log("  Bids:")
        for p in range(4):
            bid = all_bids.get(p, 0)
            self._log(f"    Player {p}{self._me(p)}: {bid}")
        self._log(f"  Winner: Player {winner}{self._me(winner)} with bid {winning_bid}")
        if gems_won:
            gems_won_str = ", ".join(g.value for g in gems_won)
            self._log(f"  Gems won: {gems_won_str}")

        # Update available gems
        for gem in gems_won:
            for i, avail in enumerate(self._last_available_gems):
                if avail == gem:
                    self._last_available_gems.pop(i)
                    break

    def log_card_revealed(self, player_id: int, card: GemType) -> None:
        # CSV
        if self._reveals_writer:
            self._reveals_writer.writerow(
                [
                    self._auction_num,
                    player_id,
                    card.value,
                    1 if player_id == self._player_id else 0,
                ]
            )
            self._reveals_file.flush()

        # Transcript
        self._log(
            f"  -> Player {player_id}{self._me(player_id)} revealed: {card.value}"
        )

    def log_gems_replenished(self, new_gems: list[GemType]) -> None:
        self._last_available_gems.extend(new_gems)
        if new_gems:
            gems_str = ", ".join(g.value for g in new_gems)
            self._log(f"  -> New gems available: {gems_str}")

    def log_mission_completed(
        self, player_id: int, mission: MissionCard, gems_used: list[GemType]
    ) -> None:
        gems_str = " + ".join(g.value for g in gems_used)

        # CSV
        if self._missions_writer:
            self._missions_writer.writerow(
                [
                    self._auction_num,
                    player_id,
                    mission.mission_id,
                    mission.reward,
                    gems_str,
                    1 if player_id == self._player_id else 0,
                ]
            )
            self._missions_file.flush()

        # Transcript
        self._log(
            f"  -> Player {player_id}{self._me(player_id)} completed Mission {mission.mission_id}!"
        )
        self._log(f"     Used: {gems_str} -> Earned {mission.reward} coins")

    def end_game(self, final_scores: dict[int, int], winner: int) -> None:
        my_score = final_scores.get(self._player_id, 0)
        i_won = 1 if winner == self._player_id else 0

        # Summary CSV
        if self._summary_writer:
            self._summary_writer.writerow(
                [
                    self._game_num,
                    self._game_id,
                    self.mode,
                    self._bot_level or "",
                    self._player_id,
                    self._started_at,
                    my_score,
                    winner,
                    i_won,
                    final_scores.get(0, 0),
                    final_scores.get(1, 0),
                    final_scores.get(2, 0),
                    final_scores.get(3, 0),
                ]
            )
            self._summary_file.flush()

        # Transcript
        self._log("")
        self._log("-" * 60)
        self._log("FINAL SCORES")
        self._log("-" * 60)
        for p in sorted(final_scores.keys()):
            score = final_scores[p]
            self._log(f"  Player {p}{self._me(p)}: {score} coins")
        self._log("")
        result_str = "I WON!" if i_won else f"Player {winner} won"
        self._log(f"Result: {result_str}")
        self._log("=" * 60)

        # Write transcript and close game files
        self._write_transcript()
        self._close_game_files()

    def close(self) -> None:
        self._close_game_files()
        if self._summary_file:
            try:
                self._summary_file.close()
            except Exception:
                pass


# === Bot Base Class ===


class AlgogemBot(ABC):
    """Abstract base class for ALGOGEM bots.

    Subclass this and implement the two required methods:
        - get_bid(): Return your bid amount for an auction
        - choose_card_to_reveal(): Choose which card to reveal from your hand

    The base class automatically tracks game state for you:
        - self.coins: Your current coin balance
        - self.hand: Your current hand of gem cards
        - self.collection: Gems you've won in auctions
        - self.player_coins: All players' coin balances (player_id -> coins)
        - self.revealed_cards: Cards revealed to value display (gem_type -> count).
            This is updated automatically on every on_card_revealed() call.
            Use it to estimate final gem values!
        - self.available_gems: Gems currently available for auction
        - self.player_names: Names of all players in this game (list of strings,
            indexed by player_id)
    """

    def __init__(self, enable_logging: bool = True, log_dir: str = "./game_data"):
        """Initialize the bot.

        Args:
            enable_logging: If True, log game data to CSV files (default: True).
            log_dir: Directory for log files (default: ./game_data).
        """
        self.player_id: int | None = None
        self.player_name: str | None = None

        # Game state - automatically updated by base class
        self.coins: int = 0
        self.hand: list[GemType] = []
        self.collection: list[GemType] = []
        self.player_coins: dict[int, int] = {}  # player_id -> coins
        self.revealed_cards: dict[GemType, int] = {}  # GemType -> count
        self.available_gems: list[GemType] = []
        self.player_names: list[str] = []  # Names of all players, indexed by player_id

        # Round/game progress (set at game_start, None in practice mode)
        self.round_number: int | None = None
        self.game_number: int | None = None
        self.games_per_round: int | None = None

        # Session record (updated by the default on_game_end)
        self._session_games: int = 0
        self._session_wins: int = 0

        # Logging
        self._logger: GameLogger | None = None
        self._enable_logging = enable_logging
        self._log_dir = log_dir

    def _init_logger(self, mode: str) -> None:
        """Initialize the logger (called by client after mode is known)."""
        if self._enable_logging:
            self._logger = GameLogger(data_dir=self._log_dir, mode=mode)

    # === REQUIRED METHODS - YOU MUST IMPLEMENT THESE ===

    @abstractmethod
    def get_bid(
        self,
        auction_card: AuctionCard,
        available_gems: list[GemType],
    ) -> int:
        """Return your bid amount for this auction.

        Args:
            auction_card: The auction being bid on. Has:
                - auction_type:
                    "treasure_1" (win 1 gem)
                    "treasure_2" (win 2 gems)
                    "loan" (get coins now, repay at end)
                    "invest" (lock coins, get bonus at end)
                - value: The loan/investment amount (None for treasure)

            available_gems: The gem(s) you can win. Each has:
                - gem_type: "green", "blue", "pink", "purple", or "orange"

        Returns:
            Your bid amount (0 or higher).
            - For treasure/invest: bid up to your current coins
            - For loans: can bid up to coins + loan value
            - If you bid more than allowed, it becomes 0
        """
        pass

    @abstractmethod
    def choose_card_to_reveal(self, hand: list[GemType]) -> int:
        """Return which card to reveal from your hand.

        After winning an auction, you must reveal one card from your hand
        to the "value display". Gems in the value display determine how
        much each gem type is worth at the end of the game.

        Args:
            hand: Your current hand of gem cards.

        Returns:
            Index of card to reveal (0 to len(hand)-1).
        """
        pass

    # === OPTIONAL EVENT HANDLERS - Override to track game state ===

    def on_game_start(
        self,
        player_id: int,
        hand: list[GemType],
        num_players: int,
        starting_coins: int,
        available_gems: list[GemType],
        available_missions: list[MissionCard],
        value_chart: dict[int, int],
        round_number: int | None = None,
        game_number: int | None = None,
        games_per_round: int | None = None,
        player_names: list[str] | None = None,
    ) -> None:
        """Called when a new game starts.

        Args:
            player_id: Your player ID (0-3).
            hand: Your starting hand of 4 gem cards.
            num_players: Number of players (always 4).
            starting_coins: Starting coins per player (usually 25).
            available_gems: Face-up gems available for auction.
            available_missions: Available mission cards (complete for bonus).
            value_chart: Mapping of count_in_display -> coin_value (e.g., {0: 0, 1: 4, ...}).
            round_number: Current round number (None in practice mode).
            game_number: Current game number within the round (None in practice mode).
            games_per_round: Total games per round (None in practice mode).
            player_names: Names of all players, indexed by player_id.
        """
        self.player_id = player_id
        # Initialize game state
        self.coins = starting_coins
        self.hand = list(hand)
        self.collection = []
        self.player_coins = {i: starting_coins for i in range(num_players)}
        self.revealed_cards = {}
        self.available_gems = list(available_gems)
        self.player_names = player_names or [
            f"Player {i}" for i in range(num_players)
        ]

        # Round/game progress
        self.round_number = round_number
        self.game_number = game_number
        self.games_per_round = games_per_round

        # Log game start
        if self._logger:
            self._logger.start_game(
                player_id,
                hand,
                starting_coins,
                available_gems,
                available_missions,
                value_chart,
            )

    def on_auction_result(
        self,
        auction_card: AuctionCard,
        winner: int,
        winning_bid: int,
        all_bids: dict[int, int],
        gems_won: list[GemType],
    ) -> None:
        """Called after an auction resolves.

        Args:
            auction_card: The auction that was resolved.
            winner: Player ID of the winner.
            winning_bid: The winning bid amount.
            all_bids: All bids (player_id -> amount).
            gems_won: Gems the winner received.
        """
        # Update winner's coins
        if winner in self.player_coins:
            self.player_coins[winner] -= winning_bid
            if auction_card.auction_type == "loan":
                self.player_coins[winner] += auction_card.value

        # Update our own state if we won
        if winner == self.player_id:
            self.coins = self.player_coins.get(winner, self.coins)
            self.collection.extend(gems_won)

        # Remove won gems from available pool
        for gem in gems_won:
            for i, avail in enumerate(self.available_gems):
                if avail == gem:
                    self.available_gems.pop(i)
                    break

        # Log auction result
        if self._logger:
            self._logger.log_auction_result(
                auction_card, winner, winning_bid, all_bids, gems_won
            )

    def on_card_revealed(self, player_id: int, card: GemType | None) -> None:
        """Called when a player reveals a card to the value display.

        Args:
            player_id: Who revealed the card.
            card: The revealed card, or None if the player's hand was empty
                (reveal was attempted but no card was available).
        """
        if card is None:
            # Null reveal - hand was empty, nothing to track
            return

        # Track revealed cards
        self.revealed_cards[card] = self.revealed_cards.get(card, 0) + 1

        # Update our hand if we revealed
        if player_id == self.player_id:
            for i, hand_card in enumerate(self.hand):
                if hand_card == card:
                    self.hand.pop(i)
                    break

        # Log card reveal
        if self._logger:
            self._logger.log_card_revealed(player_id, card)

    def on_gems_replenished(self, new_gems: list[GemType]) -> None:
        """Called when new gems are added to the auction pool.

        Args:
            new_gems: The newly revealed gems.
        """
        self.available_gems.extend(new_gems)

        # Log gems replenished
        if self._logger:
            self._logger.log_gems_replenished(new_gems)

    def on_mission_completed(
        self,
        player_id: int,
        mission: MissionCard,
        gems_used: list[GemType],
    ) -> None:
        """Called when a player completes a mission.

        Args:
            player_id: Who completed the mission.
            mission: The completed mission.
            gems_used: Gems used for completion.
        """
        if self._logger:
            self._logger.log_mission_completed(player_id, mission, gems_used)

    def on_game_end(self, final_scores: dict[int, int], winner: int) -> None:
        """Called when the game ends.

        The default implementation prints the game result and updates the game
        log. Override to customize (call super().on_game_end(...) to keep both).

        Args:
            final_scores: Final scores (player_id -> score).
            winner: Player ID of the winner.
        """
        if self._logger:
            self._logger.end_game(final_scores, winner)

        self._session_games += 1
        i_won = winner == self.player_id
        if i_won:
            self._session_wins += 1

        def fmt_player(pid: int) -> str:
            if pid < len(self.player_names):
                name = self.player_names[pid]
            else:
                name = f"Player {pid}"
            if pid == self.player_id:
                name += " (me)"
            return f"{name}={final_scores[pid]}"

        scores_str = ", ".join(fmt_player(pid) for pid in sorted(final_scores))
        result = "WON " if i_won else "lost"
        print(
            f"Game {self._session_games}: {result} [{scores_str}]  "
            f"(session record: {self._session_wins}W / {self._session_games} games)"
        )

    def on_round_complete(
        self,
        games_played: int,
        standings: list[dict[str, Any]],
        next_round_in: float,
        round_number: int | None = None,
    ) -> None:
        """Called when a round of games completes.

        Args:
            games_played: Number of games in the round.
            standings: Current standings list.
            next_round_in: Seconds until next round.
            round_number: The round that just completed (None if not provided).
        """
        round_str = f"Round {round_number}" if round_number is not None else "Round"
        mine = next((s for s in standings if s.get("name") == self.player_name), None)
        if mine is not None:
            print(
                f"--- {round_str} complete: you are #{mine.get('rank')} of "
                f"{len(standings)} ({mine.get('games_won')} wins in "
                f"{mine.get('games_played')} games). "
                f"Next round in {next_round_in:.0f}s ---"
            )
        else:
            print(f"--- {round_str} complete. Next round in {next_round_in:.0f}s ---")

    # === PRACTICE MODE CALLBACKS ===

    def on_practice_status(
        self,
        current_level: int,
        current_bot_name: str,
        games_played: int,
        wins: int,
        tier: str,
        avg_score: float,
        level_stats: list[dict[str, Any]],
    ) -> None:
        """Called after each practice game with your current stats.

        Args:
            current_level: Level number of bot you're playing against (1=easiest, 24=hardest).
            current_bot_name: Name of the bot you're playing against.
            games_played: Total practice games played.
            wins: Total practice wins.
            tier: Your tier (Novice/Bronze/Silver/Gold/Platinum/Diamond/Master/Grandmaster).
            avg_score: Your average score per game.
            level_stats: Per-level statistics list.
        """
        # Update logger with current bot level
        if self._logger:
            self._logger.set_bot_level(current_level)

    def on_level_up(
        self,
        new_level: int,
        new_bot_name: str,
        tier: str,
    ) -> None:
        """Called when you advance to a harder bot level.

        The default implementation prints the level-up. Override to customize.

        Args:
            new_level: Tier number of the new bot (lower = harder).
            new_bot_name: Name of the new bot you'll face.
            tier: Your new tier after leveling up.
        """
        print(f"*** LEVEL UP! Now facing L{new_level}: {new_bot_name} (tier: {tier}) ***")

    def on_reject(self, reason: str, action: str, selected_value: int) -> None:
        """Called when server rejected your response and auto-selected.

        Default implementation logs to game_data/rejections.csv.

        Args:
            reason: "timeout" or "invalid"
            action: "bid" or "reveal"
            selected_value: The value the server used instead
        """
        game_data_dir = Path(self._log_dir)
        game_data_dir.mkdir(exist_ok=True)
        csv_path = game_data_dir / "rejections.csv"

        file_exists = csv_path.exists()
        with open(csv_path, "a", newline="") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["timestamp", "reason", "action", "selected_value"])
            writer.writerow([datetime.now().isoformat(), reason, action, selected_value])

    def on_practice_complete(
        self,
        total_games: int,
        wins: int,
        losses: int,
        final_level: int,
        total_levels: int,
        avg_score: float,
        win_rate: float,
        level_stats: list[dict[str, Any]],
    ) -> None:
        """Called when a practice session completes (300 games).

        After this callback, the server will disconnect you.

        Args:
            total_games: Total games played in session (300).
            wins: Total wins.
            losses: Total losses.
            final_level: Level reached (1-indexed, higher = harder).
            total_levels: Total number of levels available.
            avg_score: Average score per game.
            win_rate: Overall win rate (0.0 to 1.0).
            level_stats: Per-level statistics [{name, games, wins, win_rate}, ...]
        """
        # Default: print a summary
        print("\n" + "=" * 60)
        print("PRACTICE SESSION COMPLETE")
        print("=" * 60)
        print(f"Games Played: {total_games}")
        print(f"Record: {wins}W / {losses}L ({win_rate:.1%} win rate)")
        print(f"Final Level: L{final_level} / {total_levels}")
        print(f"Average Score: {avg_score:.1f}")
        if level_stats:
            print("\nPer-Level Breakdown:")
            for ls in level_stats:
                print(
                    f"  {ls['name']}: {ls['games']} games, "
                    f"{ls['wins']}W ({ls['win_rate']:.0%})"
                )
        print("=" * 60 + "\n")


# === Network Client ===


class _AlgogemClient:
    """Network client for connecting to ALGOGEM server."""

    def __init__(
        self,
        bot: AlgogemBot,
        server: str,
        port: int,
        token: str,
        name: str,
        mode: str = "pvp",
    ):
        self.bot = bot
        self.server = server
        self.port = port
        self.token = token
        self.name = name
        self.mode = mode  # "practice" or "pvp"
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False

    async def connect(self) -> bool:
        try:
            print(f"Connecting to {self.server}:{self.port} (mode={self.mode})...")
            self._reader, self._writer = await asyncio.open_connection(
                self.server, self.port
            )

            auth_msg = {
                "type": "auth",
                "token": self.token,
                "name": self.name,
                "mode": self.mode,
            }
            await self._send(auth_msg)

            response = await self._receive()
            if response is None:
                logger.error("Connection closed during authentication")
                return False

            # Handle mode rejection
            if response.get("type") == "mode_reject":
                reason = response.get("reason", "Mode not allowed")
                logger.error(f"Mode rejected: {reason}")
                return False

            if response.get("type") != "auth_result":
                logger.error(f"Unexpected response: {response}")
                return False

            if not response.get("success"):
                error = response.get("error", "Unknown error")
                logger.error(f"Authentication failed: {error}")
                return False

            self.bot.player_name = response.get("player_name", self.name)
            self._connected = True

            # Initialize the bot's logger with the connection mode
            self.bot._init_logger(self.mode)

            print()
            print("=" * 60)
            print(f"  Connected to ALGOGEM server as: {self.bot.player_name}")
            print(f"  Mode: {self.mode}")
            if self.bot._enable_logging:
                print(f"  Game data will be logged to: {self.bot._log_dir}/")
            else:
                print("  Game data logging: disabled")
            print("  Game results will print below as they happen.")
            print("  Press Ctrl+C to disconnect.")
            print("=" * 60)
            print()
            return True

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    async def disconnect(self) -> None:
        self._connected = False
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._reader = None
        self._writer = None

    async def run(self) -> None:
        if not self._connected:
            if not await self.connect():
                return

        try:
            while self._connected:
                msg = await self._receive()
                if msg is None:
                    print("\nServer closed the connection.")
                    break
                try:
                    await self._handle_message(msg)
                except Exception as e:
                    # A crash in bot code (e.g. a type error in an event
                    # callback) shouldn't kill the connection - log it and
                    # keep playing. The server substitutes default actions
                    # for any response we failed to send.
                    logger.error(f"Error handling {msg.get('type')} message: {e}")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in client loop: {e}")
        finally:
            await self.disconnect()
            self._print_goodbye()

    def _print_goodbye(self) -> None:
        """Print a session summary pointing at the log files."""
        print("Disconnected from ALGOGEM server.")
        game_logger = self.bot._logger
        session_dir = game_logger.session_dir if game_logger else None
        if session_dir is not None:
            print(f"Game logs for this session: {session_dir.resolve()}/")
            print(
                "  summary.csv has one row per game; each game_* folder has a "
                "transcript and per-auction CSVs."
            )

    async def _send(self, msg: dict[str, Any]) -> None:
        if self._writer is None:
            raise RuntimeError("Not connected")
        data = json.dumps(msg) + "\n"
        self._writer.write(data.encode("utf-8"))
        await self._writer.drain()

    async def _receive(self) -> dict[str, Any] | None:
        if self._reader is None:
            return None
        try:
            line = await self._reader.readline()
            if not line:
                return None
            return json.loads(line.decode("utf-8").strip())
        except Exception as e:
            logger.error(f"Error receiving message: {e}")
            return None

    async def _handle_message(self, msg: dict[str, Any]) -> None:
        msg_type = msg.get("type")

        if msg_type == "ping":
            await self._send({"type": "pong"})

        elif msg_type == "waiting":
            # Silently ignore waiting messages
            pass

        elif msg_type == "game_start":
            # Parse value_chart - convert string keys to int (JSON transmits keys as strings)
            raw_value_chart = msg.get("value_chart", {})
            if isinstance(raw_value_chart, dict):
                value_chart = {int(k): v for k, v in raw_value_chart.items()}
            else:
                # Backwards compatibility: if server sends old string format, use default ChartA
                value_chart = {i: i * 4 for i in range(7)}
            self.bot.on_game_start(
                player_id=msg["player_id"],
                hand=[_parse_gem(g) for g in msg["hand"]],
                num_players=msg.get("num_players", 4),
                starting_coins=msg.get("starting_coins", 25),
                available_gems=[
                    _parse_gem(g) for g in msg.get("available_gems", [])
                ],
                available_missions=[
                    _parse_mission_card(m) for m in msg.get("available_missions", [])
                ],
                value_chart=value_chart,
                round_number=msg.get("round_number"),
                game_number=msg.get("game_number"),
                games_per_round=msg.get("games_per_round"),
                player_names=msg.get("player_names"),
            )

        elif msg_type == "bid_request":
            auction_card = _parse_auction_card(msg["auction_card"])
            available_gems = [_parse_gem(g) for g in msg.get("available_gems", [])]

            try:
                bid = int(self.bot.get_bid(auction_card, available_gems))
            except Exception as e:
                logger.error(f"Error in get_bid: {e}")
                bid = 0

            await self._send({"type": "bid", "amount": bid})

        elif msg_type == "reveal_request":
            hand = [_parse_gem(g) for g in msg["hand"]]

            try:
                card_index = int(self.bot.choose_card_to_reveal(hand))
            except Exception as e:
                logger.error(f"Error in choose_card_to_reveal: {e}")
                card_index = 0

            await self._send({"type": "reveal", "card_index": card_index})

        elif msg_type == "auction_result":
            all_bids = {int(k): v for k, v in msg.get("all_bids", {}).items()}
            self.bot.on_auction_result(
                auction_card=_parse_auction_card(msg["auction_card"]),
                winner=msg["winner"],
                winning_bid=msg["winning_bid"],
                all_bids=all_bids,
                gems_won=[_parse_gem(g) for g in msg.get("gems_won", [])],
            )

        elif msg_type == "card_revealed":
            raw_card = msg.get("card")
            card = _parse_gem(raw_card) if raw_card is not None else None
            self.bot.on_card_revealed(
                player_id=msg["player_id"],
                card=card,
            )

        elif msg_type == "gems_replenished":
            self.bot.on_gems_replenished(
                new_gems=[_parse_gem(g) for g in msg.get("new_gems", [])],
            )

        elif msg_type == "mission_completed":
            self.bot.on_mission_completed(
                player_id=msg["player_id"],
                mission=_parse_mission_card(msg["mission"]),
                gems_used=[_parse_gem(g) for g in msg.get("gems_used", [])],
            )

        elif msg_type == "game_end":
            final_scores = {int(k): v for k, v in msg.get("final_scores", {}).items()}
            self.bot.on_game_end(
                final_scores=final_scores,
                winner=msg["winner"],
            )

        elif msg_type == "round_complete":
            self.bot.on_round_complete(
                games_played=msg.get("games_played", 0),
                standings=msg.get("standings", []),
                next_round_in=msg.get("next_round_in", 0),
                round_number=msg.get("round_number"),
            )

        # Practice mode messages
        elif msg_type == "practice_status":
            self.bot.on_practice_status(
                current_level=msg.get("current_level", 22),
                current_bot_name=msg.get("current_bot_name", "Unknown"),
                games_played=msg.get("games_played", 0),
                wins=msg.get("wins", 0),
                tier=msg.get("tier", "Novice"),
                avg_score=msg.get("avg_score", 0.0),
                level_stats=msg.get("level_stats", []),
            )

        elif msg_type == "level_up":
            self.bot.on_level_up(
                new_level=msg.get("new_level", 22),
                new_bot_name=msg.get("new_bot_name", "Unknown"),
                tier=msg.get("tier", "Novice"),
            )

        elif msg_type == "practice_complete":
            self.bot.on_practice_complete(
                total_games=msg.get("total_games", 100),
                wins=msg.get("wins", 0),
                losses=msg.get("losses", 0),
                final_level=msg.get("final_level", 1),
                total_levels=msg.get("total_levels", 1),
                avg_score=msg.get("avg_score", 0.0),
                win_rate=msg.get("win_rate", 0.0),
                level_stats=msg.get("level_stats", []),
            )

        elif msg_type == "mode_reject":
            reason = msg.get("reason", "Mode not allowed")
            logger.error(f"Mode rejected: {reason}")
            self._connected = False

        elif msg_type == "reject":
            self.bot.on_reject(
                reason=msg.get("reason", "unknown"),
                action=msg.get("action", "unknown"),
                selected_value=msg.get("selected_value", 0),
            )

        elif msg_type == "error":
            logger.error(f"Server error: {msg.get('error')}")


# === Public API ===


def run_bot(
    bot: AlgogemBot,
    server: str = "localhost",
    port: int = 5000,
    token: str = "",
    name: str = "",
    mode: str = "pvp",
) -> None:
    """Run a bot, connecting to the ALGOGEM server.

    Args:
        bot: Your bot implementation (subclass of AlgogemBot).
        server: Server hostname or IP address.
        port: Server port (default: 5000).
        token: Your authentication token.
        name: Optional display name (server may override).
        mode: Connection mode - "pvp" for competition against other teams,
              "practice" for playing against starter bots. Default: "pvp".
    """
    client = _AlgogemClient(
        bot=bot,
        server=server,
        port=port,
        token=token,
        name=name,
        mode=mode,
    )
    asyncio.run(client.run())


if __name__ == "__main__":
    import argparse

    from algogem_bot import MyBot

    parser = argparse.ArgumentParser(
        description="ALGOGEM Bot Client - Connect to server and play!",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example usage:
  python algogem_client.py --server 192.168.1.42 --token abc123 --mode practice
  python algogem_client.py -s localhost -t mytoken -m pvp --no-log
""",
    )
    parser.add_argument("--server", "-s", default="localhost", help="Server address")
    parser.add_argument("--port", "-p", type=int, default=5000, help="Server port")
    parser.add_argument("--token", "-t", required=True, help="Your auth token")
    parser.add_argument(
        "--mode",
        "-m",
        required=True,
        choices=["practice", "pvp"],
        help="Game mode: practice (vs bots) or pvp (vs other teams)",
    )
    parser.add_argument(
        "--no-log",
        action="store_true",
        help="Disable game data logging (enabled by default)",
    )
    parser.add_argument(
        "--log-dir",
        default="./game_data",
        help="Directory for game data logs (default: ./game_data)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(message)s")

    try:
        run_bot(
            MyBot(enable_logging=not args.no_log, log_dir=args.log_dir),
            server=args.server,
            port=args.port,
            token=args.token,
            mode=args.mode,
        )
    except KeyboardInterrupt:
        pass
