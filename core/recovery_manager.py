class RecoveryManager:
    """
    MÓDULO DE RECUPERAÇÃO INTELIGENTE (ANTI-GALE)
    Focado em Capital Recovery sem exposição agressiva.
    """
    
    def __init__(self, base_stake=2):
        self.base_stake = base_stake
        self.current_loss = 0

    def calculate_next_stake(self, last_result, last_stake, payout=0.85):
        """
        Calcula a próxima mão baseada no resultado anterior.
        Se houve Loss, busca recuperar em 2 etapas (SorosGale Suave).
        """
        if last_result == "WIN":
            self.current_loss = 0
            return self.base_stake
        
        elif last_result == "LOSS":
            self.current_loss += last_stake
            # Em vez de dobrar (4.0), busca recuperar metade do loss + entrada base
            # Ex: Loss de 2 -> Próxima: 2 (base) + 1 (recuperação parcial) = 3
            recovery_stake = self.base_stake + (self.current_loss * 0.5)
            return round(recovery_stake, 2)
            
        return self.base_stake
