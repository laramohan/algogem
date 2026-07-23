"""ALGOGEM Bot - This is the file you edit to create your bot!

Implement your strategy by editing the MyBot class below.
Run with: python algogem_client.py --server <ip> --token <token> --mode practice

Data types available to you:
    GemType      - Enum: GREEN, BLUE, PINK, PURPLE, ORANGE
    AuctionCard  - Has auction_type ("treasure_1", "treasure_2", "loan", "invest")
                   and value (loan/invest amount, None for treasure)
    MissionCard  - Has mission_id, required_gems, reward, mission_type, wildcard_count

State tracked for you by the base class (access via self.*):
    coins          - Your current coin balance
    hand           - Your current hand (list of GemType)
    collection     - Gems you've won in auctions (list of GemType)
    player_coins   - All players' coin balances {player_id: coins}
    revealed_cards - Cards in the value display {GemType: count}
    available_gems - Gems currently available for auction (list of GemType)
    player_names   - Names of all players [str, ...]
"""

from algogem_client import AlgogemBot, AuctionCard, GemType, MissionCard  # noqa: F401


class MyBot(AlgogemBot):
    """Your bot - implement the two required methods below.

    The base class automatically tracks game state for you:
        self.coins           - Your current coin balance
        self.hand            - Your current hand (list of GemType)
        self.collection      - Gems you've won in auctions
        self.player_coins    - All players' coin balances {player_id: coins}
        self.revealed_cards  - Cards in the value display {GemType: count}
        self.available_gems  - Gems currently available for auction
        self.player_names    - Names of all players [str, ...]
    """

    # --- REQUIRED: You must implement these two methods ---

    def get_bid(
        self, auction_card: AuctionCard, available_gems: list[GemType]) -> int:
        """Return your bid amount for this auction.

        This is called every auction. All 4 players bid simultaneously
        (sealed bid). Highest bidder wins; ties broken by seat order.

        Args:
            auction_card: The auction being bid on.
                .auction_type (str): What's being auctioned.
                    "treasure_1" - Winner pays bid, gets 1 gem from the pool
                    "treasure_2" - Winner pays bid, gets 2 gems from the pool
                    "loan"       - Winner pays bid, gets loan coins now,
                                   must repay loan value at game end
                    "invest"     - Winner pays bid, locks bid coins,
                                   gets bid + investment value at game end
                .value (int | None): The loan/investment amount.
                    None for treasure auctions.
                    For "loan": how many coins you receive now (and repay at end)
                    For "invest": bonus coins you receive at end on top of your bid

            available_gems: The face-up gem(s) you'd win (for treasure auctions).
                Each is a GemType enum value (e.g., GemType.GREEN).
                Empty list for loan/invest auctions.

        Returns:
            Your bid (0 or higher).
            - For treasure/invest: you can bid 0 up to your current coins
            - For loans: you can bid 0 up to coins + loan value
            - If your bid exceeds the allowed max, it defaults to 0
        """
        gem1 = ""
        gem2 = ""
        bid = 0
        if (auction_card.auction_type in ["treasure_1"]):
            gem1 = available_gems[0].name
                
            numGemRevealed = self.revealed_cards[gem1]
            print(numGemRevealed)
            # will run into issue since a gem is double counted
            secretGem = self.hand[gem1]
            bid = 2 * (numGemRevealed + secretGem) + 1
        if (auction_card.auction_type in ["treasure_2"]):
            gem1 = available_gems[0].name
            gem2 = available_gems[1].name
            numGemRevealed1 = self.revealed_cards[gem1]
            secretGem1 = self.hand[gem1]
            numGemRevealed2 = self.revealed_cards[gem2]
            secretGem2 = self.hand[gem2]
            bid = 2 * (numGemRevealed1 + secretGem1 + numGemRevealed2 + secretGem2) + 1
        elif (auction_card.auction_type in ["loan"]):
            bid = 0.5 * auction_card.value
        elif (auction_card.auction_type in ["invest"]):
            bid = 0.5 * auction_card.value
        return bid

        raise NotImplementedError("Implement your bidding strategy here")

    def choose_card_to_reveal(self, hand: list[GemType]) -> int:
        """Return which card to reveal from your hand (0 to len(hand)-1).

        After winning an auction, you must reveal one card from your hand
        to the "value display". The number of each gem type in the value
        display determines how much that gem type is worth at game end
        (see the value_chart passed in on_game_start).

        Args:
            hand: Your current hand of gem cards (list of GemType).

        Returns:
            Index of the card to reveal (0 to len(hand)-1).
        """
        ind = -1
        for avail_gem in self.available_gems:
            if avail_gem in hand and avail_gem in self.not_revealed: #(make sure to check for if one is revealed but u have one more):
            # hmm interesting there's no set data structure to hold the cards that you've revealed
                ind = hand.index(self.available_gems)
        # will run into an issue when two of same gem type in hand, one is revealed
        else:
            sorted_abundance = {k: v for (k,v) in self.revealed_cards.values.sort()}
            for i in range(len(sorted_abundance)-1,-1,-1):
                if sorted_abundance[i] in hand and sorted_abundance[i] in self.not_revealed:
                    ind = hand.index(self.available_gems)
                    self.on_card_revealed(self.player_id,i)
        self.not_revealed.remove(hand[ind])
        return ind

        raise NotImplementedError("Implement your reveal strategy here")

    # --- OPTIONAL: Override any of these to hook into game events ---
    # See AlgogemBot in algogem_client.py for the full list of callbacks.
    #
    # def on_game_start(self, player_id, hand, num_players, starting_coins,
    #                   available_gems, available_missions, value_chart,
    #                   round_number=None, game_number=None,
    #                   games_per_round=None, player_names=None):
    #     super().on_game_start(player_id, hand, num_players, starting_coins,
    #                           available_gems, available_missions, value_chart,
    #                           round_number, game_number, games_per_round,
    #                           player_names)
    #     # Your custom game-start logic here
    #
    # def on_auction_result(self, auction_card, winner, winning_bid,
    #                       all_bids, gems_won):
    #     super().on_auction_result(auction_card, winner, winning_bid,
    #                               all_bids, gems_won)
    #
    # def on_card_revealed(self, player_id, card):
    #     super().on_card_revealed(player_id, card)
    #     # card is None if the player's hand was empty
    #
    # def on_game_end(self, final_scores, winner):
    #     super().on_game_end(final_scores, winner)
