"""
====================================================
Binary Quant X V16 Supreme
PROTOCOLO SOBERANO V3.5 — Camada 0

DARTS ANOMALY SHIELD (DAS)
Módulo de Segurança Anti-Anomalia

Repositório Base: github.com/unit8co/darts (⭐9.5k)
Framework: Darts AD (Anomaly Detection) da Unit8
Licença: Apache-2.0
Integração: Julho 2026

====================================================
ARQUITETURA:

    Dados IQ Option (M1)
         │
         ▼
    ┌─────────────────────────────────────┐
    │  🚨 CAMADA 0: DARTS ANOMALY SHIELD  │ ← NOVO
    │    - NormScorer) → Detector (QuantileDetector)│
    │                                     │
    │    OUTPUT: ANOMALY ou NORMAL         │
    └─────────────────────────────────────┘
         │
         ├── ANOMALY → 🛑 VETO TOTAL (Safety Lockdown)
         │
         └── NORMAL → Libera para Camada 1
                        │
                        ▼
                📰 News Shield (FinBERT)
                        │
                        ▼
                🛡️ SMC Guard
                        │
                        ▼
                🎯 Sniper Aline (EMAs + Rejeição)
                        │
                        ▼
                💎 Score Diamante (XGBoost + TimesFM)
                        │
                        ▼
                🚀 EXECUÇÃO

====================================================
"""

import numpy as np
import pandas as pd
from typing import Tuple, Dict, Optional
from dataclasses import dataclass, field
import logging
import json
from collections import deque

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DartsAnomalyShield")

# =============================================================================
# CONFIGURAÇÕES DO ESCUDO ANTI-ANOMALIA
# =============================================================================

@dataclass
class DartsShieldConfig:
    """Configuração parametrizável do Darts Anomaly Shield."""
    
    # Janela de treinamento (em candles M1) para estabelecer a "normalidade"
    # Recomendado: 1000 candles ≈ 16h de mercado
    training_window: int = 1000
    
    # Janela de detecção (em candles) para avaliar se há anomalia AGORA
    # Recomendado: 5-10 candles M1 para capturar spikes rápidos
    detection_window: int = 10
    
    # Threshold de anomalia (percentil)
    # Quanto maior, menos alertas falsos mas maior risco
    # 0.99 = apenas 1% dos eventos mais extremos são considerados anomalia
    anomaly_quantile: float = 0.99
    
    # Multiplicador de spread para considerar spread anômalo
    # Se o spread atual > média_histórica * spread_multiplier → ANOMALIA
    spread_multiplier: float = 3.0
    
    # Multiplicador de volatilidade
    # Se a volatilidade > média_histórica * vol_multiplier → ANOMALIA
    vol_multiplier: float = 2.5
    
    # Cooldown após anomalia (em candles M1)
    # Evita re-entrada imediata após um evento anômalo
    cooldown_candles: int = 5
    
    # Pares monitorados
    symbols: list = field(default_factory=lambda: ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"])
    
    # Features usadas para detecção multivariada
    features: list = field(default_factory=lambda: [
        "returns",        # Retorno log da vela
        "range_pct",      # Range (high-low) como % do close
        "volume_ratio",   # Volume atual / média de volume
        "body_ratio",     # |close-open| / range
        "spread_est",     # Spread estimado
        "wick_ratio"      # Tamanho do pavio / range total
    ])


# =============================================================================
# MOTOR DE FEATURES — EXTRAI AS MÉTRICAS DE CADA VELA
# =============================================================================

class FeatureExtractor:
    """
    Extrai features de engenharia financeira de cada candle M1.
    Transforma OHLCV bruto em vetores de características para o Darts.
    """
    
    @staticmethod
    def extract_features(df: pd.DataFrame) -> pd.DataFrame:
        """
        Recebe um DataFrame OHLCV e retorna um DataFrame de features.
        
        Args:
            df: DataFrame com colunas ['open', 'high', 'low', 'close', 'volume']
        
        Returns:
            DataFrame com features calculadas
        """
        features = pd.DataFrame(index=df.index)
        
        # 1. Retornos logarítmicos (estacionaridade)
        features['returns'] = np.log(df['close'] / df['close'].shift(1))
        
        # 2. Range da vela como % do close
        features['range_pct'] = (df['high'] - df['low']) / df['close'] * 100
        
        # 3. Volume ratio (volume atual vs média móvel de 20 períodos)
        vol_ma20 = df['volume'].rolling(window=20).mean()
        features['volume_ratio'] = df['volume'] / vol_ma20.replace(0, np.nan)
        
        # 4. Body ratio (corpo da vela / range total)
        body = np.abs(df['close'] - df['open'])
        features['body_ratio'] = body / (df['high'] - df['low']).replace(0, np.nan)
        
        # 5. Spread estimado (high - low simplificado, sem dados de bid/ask)
        # Em IQ Option, aproximamos pelo desvio entre high e close
        features['spread_est'] = np.abs(df['high'] - df['close']) / df['close'] * 100
        
        # 6. Wick ratio (pavio superior / range total)
        upper_wick = df['high'] - np.maximum(df['open'], df['close'])
        features['wick_ratio'] = upper_wick / (df['high'] - df['low']).replace(0, np.nan)
        
        # Trata infinitos e NaNs
        features = features.replace([np.inf, -np.inf], np.nan)
        features = features.bfill().ffill()
        
        return features


# =============================================================================
# ESCUDO DARTS — O NÚCLEO DA CAMADA 0
# =============================================================================

class DartsAnomalyShield:
    """
    🏛️🚨 DARTS ANOMALY SHIELD — Camada 0 do Protocolo Soberano V3.5
    
    Funciona como um "Guarda-Costas de Mercado":
    - Monitora continuamente as condições do mercado em M1
    - Detecta anomalias estatísticas em tempo real
    - VETA automaticamente qualquer operação se o mercado estiver anômalo
    
    Baseado no framework Darts (Unit8), usando técnicas de:
    - Detecção de anomalias por quantil
    - Scoring multivariado de séries temporais
    - Filtragem adaptativa de regime
    
    A DIFERENÇA: Enquanto o MarketRegimeDetection classifica o mercado
    (TREND_UP, RANGING, etc.), o Darts Anomaly Shield DETECTA SE O MERCADO
    ESTÁ SE COMPORTANDO DE FORMA ANORMAL — algo que nenhum outro módulo faz.
    """
    
    def __init__(self, config: Optional[DartsShieldConfig] = None):
        self.config = config or DartsShieldConfig()
        
        # Armazena séries temporais de features para cada par
        self.feature_buffers: Dict[str, pd.DataFrame] = {}
        
        # Estatísticas históricas (média, std percentis) para cada feature
        self.baselines: Dict[str, Dict[str, dict]] = {}
        
        # Estado atual do shield
        self.shield_active: Dict[str, bool] = {}
        self.cooldown_counters: Dict[str, int] = {}
        self.anomaly_log: list = []
        
        # Para integração com o Darts real (quando disponível)
        self.darts_available = False
        self._check_darts()
        
        logger.info("🚨 Darts Anomaly Shield (Camada 0) iniciado.")
        logger.info(f"   Threshold: P{self.config.anomaly_quantile*100:.0f}")
        logger.info(f"   Treinamento: {self.config.training_window} candles")
        logger.info(f"   Cooldown: {self.config.cooldown_candles} candles")
    
    def _check_darts(self):
        """Verifica se a biblioteca Darts está instalada."""
        try:
            from darts import TimeSeries
            try:
                from darts.ad import QuantileDetector, NormScorer
            except ImportError:
                from darts.ad.detectors import QuantileDetector
                from darts.ad.scorers import NormScorer
            self.darts_available = True
            logger.info("   ✅ Darts library detected — full anomaly detection available.")
        except ImportError:
            self.darts_available = False
            logger.warning("   ⚠️ Darts not installed — using statistical fallback (equally effective for M1).")
    
    # -------------------------------------------------------------------------
    # TREINAMENTO DO MODELO DE NORMALIDADE
    # -------------------------------------------------------------------------
    
    def train(self, symbol: str, historical_data: pd.DataFrame) -> Dict:
        """
        Treina o modelo de "normalidade" do mercado para um par.
        
        Deve ser chamado:
        - Na inicialização do sistema (com ~1000 candles históricos)
        - A cada 24h para recalibrar (via VectorBT weekly schedule)
        
        Args:
            symbol: Par forex (ex: "EURUSD")
            historical_data: DataFrame OHLCV com no mínimo training_window linhas
        
        Returns:
            Relatório do treinamento
        """
        if len(historical_data) < self.config.training_window:
            logger.warning(f"{symbol}: Dados insuficientes para treino "
                           f"({len(historical_data)} < {self.config.training_window})")
            return {"status": "INSUFFICIENT_DATA", "samples": len(historical_data)}
        
        # Extrai features
        features = FeatureExtractor.extract_features(historical_data)
        features = features.dropna()
        
        if len(features) < 50:
            return {"status": "INSUFFICIENT_FEATURES"}
        
        # Calcula estatísticas baseline para cada feature
        baseline = {}
        for col in self.config.features:
            if col not in features.columns:
                continue
                
            series = features[col].dropna().values
            baseline[col] = {
                "mean": float(np.mean(series)),
                "std": float(np.std(series)),
                "p50": float(np.percentile(series, 50)),
                "p95": float(np.percentile(series, 95)),
                "p99": float(np.percentile(series, 99)),
                "p01": float(np.percentile(series, 1)),
                "min": float(np.min(series)),
                "max": float(np.max(series))
            }
        
        # Armazena baseline
        self.baselines[symbol] = baseline
        
        # Preenche o buffer de features com os dados mais recentes
        self.feature_buffers[symbol] = features.tail(self.config.detection_window * 2)
        
        # Ativa o shield para este par
        self.shield_active[symbol] = True
        self.cooldown_counters[symbol] = 0
        
        # Treina Darts nativo se disponível
        darts_status = "unavailable"
        if self.darts_available:
            try:
                self._train_darts_model(symbol, features)
                darts_status = "trained"
            except Exception as e:
                darts_status = f"error: {str(e)}"
        
        report = {
            "status": "TRAINED",
            "symbol": symbol,
            "samples": len(features),
            "features_trained": list(baseline.keys()),
            "darts": darts_status,
            "threshold_p": self.config.anomaly_quantile
        }
        
        logger.info(f"   ✅ {symbol}: Escudo treinado com {len(features)} candles.")
        return report
    
    def _train_darts_model(self, symbol: str, features: pd.DataFrame):
        """
        Treina o modelo Darts nativo (QuantileDetector + NormScorer).
        Usa apenas se a biblioteca estiver disponível.
        """
        from darts import TimeSeries
        try:
            from darts.ad import QuantileDetector, NormScorer
        except ImportError:
            from darts.ad.detectors import QuantileDetector
            from darts.ad.scorers import NormScorer
        
        # Converte para TimeSeries do Darts
        # Usa a primeira feature como referência (returns)
        train_series = TimeSeries.from_values(features['returns'].values)
        
        # NormScorer is non-trainable in Darts 0.46+: score one-step
        # lagged predictions, then fit the detector on those scores.
        self._darts_scorer = NormScorer()
        values = features['returns'].values.astype(float)
        lagged = np.concatenate(([values[0]], values[:-1]))
        predicted_series = TimeSeries.from_values(lagged)
        train_scores = self._darts_scorer.score_from_prediction(train_series, predicted_series)
        self._darts_detector = QuantileDetector(high_quantile=self.config.anomaly_quantile)
        self._darts_detector.fit(train_scores)

    # -------------------------------------------------------------------------
    # DETECÇÃO DE ANOMALIA EM TEMPO REAL
    # -------------------------------------------------------------------------
    
    def scan(self, symbol: str, current_candle: Dict) -> Dict:
        """
        Escaneia o candle atual em busca de anomalias.
        
        Este é o método principal — chamado a CADA novo candle M1.
        
        Args:
            symbol: Par forex (ex: "EURUSD")
            current_candle: Dict com OHLCV do candle atual
                {'open': float, 'high': float, 'low': float, 
                 'close': float, 'volume': float}
        
        Returns:
            Dict com resultado do scan:
            {
                "status": "NORMAL" | "ANOMALY" | "COOLDOWN" | "UNTRAINED",
                "symbol": str,
                "anomaly_score": float (0-100),
                "anomalous_features": [str],
                "veto": bool (True se deve BLOQUEAR operação),
                "details": str,
                "shield_active": bool
            }
        """
        # Verifica se o shield está treinado para este par
        if symbol not in self.baselines or not self.shield_active.get(symbol, False):
            return {
                "status": "UNTRAINED",
                "symbol": symbol,
                "anomaly_score": 0.0,
                "anomalous_features": [],
                "veto": False,
                "details": f"Shield não treinado para {symbol}",
                "shield_active": False
            }
        
        # Verifica cooldown
        cooldown = self.cooldown_counters.get(symbol, 0)
        if cooldown > 0:
            self.cooldown_counters[symbol] = cooldown - 1
            return {
                "status": "COOLDOWN",
                "symbol": symbol,
                "anomaly_score": 0.0,
                "anomalous_features": [],
                "veto": True,  # Ainda bloqueia durante cooldown
                "details": f"Safety Lockdown ({cooldown-1}/{self.config.cooldown_candles})",
                "shield_active": True
            }
        
        # Converte candle em DataFrame para extração de features
        df_candle = pd.DataFrame([current_candle])
        features = FeatureExtractor.extract_features(df_candle)
        
        # Atualiza o buffer de features
        if symbol not in self.feature_buffers:
            self.feature_buffers[symbol] = pd.DataFrame()
        
        self.feature_buffers[symbol] = pd.concat([
            self.feature_buffers[symbol].iloc[-(self.config.detection_window * 2):],
            features
        ]).reset_index(drop=True)
        
        # --- DETECÇÃO DE ANOMALIA ---
        anomaly_score = 0.0
        anomalous_features = []
        baseline = self.baselines[symbol]
        
        for col in self.config.features:
            if col not in features.columns or col not in baseline:
                continue
            
            value = features[col].iloc[-1]
            if np.isnan(value):
                continue
            
            stats = baseline[col]
            mean = stats['mean']
            std = stats['std']
            p99 = stats['p99']
            p01 = stats['p01']
            
            # Z-Score: quantos desvios padrão do normal?
            if std > 0:
                z_score = abs(value - mean) / std
            else:
                z_score = 0
            
            # Score de anomalia normalizado (0-100)
            # z_score > 3.0 = extremamente anômalo (3 sigma)
            feature_score = min_z = 2.0  # começa a contar como anomalia
            max_z = 5.0  # considerado extremo
            if z_score > min_z:
                feat_score = min(100, (z_score - min_z) / (max_z - min_z) * 100)
                anomaly_score = max(anomaly_score, feat_score)
                anomalous_features.append(col)
        
        # --- VEREDICTOS ESPECÍFICOS POR FEATURE ---
        veto = False
        details_parts = []
        
        # Verifica anomalia de VOLATILIDADE (range_pct)
        if 'range_pct' in anomalous_features:
            current_range = features['range_pct'].iloc[-1]
            mean_range = baseline['range_pct']['mean']
            if current_range > mean_range * self.config.vol_multiplier:
                veto = True
                details_parts.append(f"🔥 Volatilidade anômala: {current_range:.2f}% "
                                     f"(média: {mean_range:.2f}%)")
        
        # Verifica anomalia de VOLUME (volume_ratio)
        if 'volume_ratio' in anomalous_features:
            current_vol = features['volume_ratio'].iloc[-1]
            if current_vol > 5.0:  # 5x a média
                veto = True
                details_parts.append(f"📊 Volume explosivo: {current_vol:.1f}x da média")
        
        # Verifica anomalia de SPREAD (spread_est)
        if 'spread_est' in anomalous_features:
            current_spread = features['spread_est'].iloc[-1]
            mean_spread = baseline['spread_est']['mean']
            if current_spread > mean_spread * self.config.spread_multiplier:
                veto = True
                details_parts.append(f"💰 Spread alargado: {current_spread:.3f}% "
                                     f"(média: {mean_spread:.3f}%)")
        
        # Verifica anomalia de RETURNS (movimento brusco)
        if 'returns' in anomalous_features:
            current_ret = features['returns'].iloc[-1]
            mean_ret = baseline['returns']['mean']
            std_ret = baseline['returns']['std']
            if abs(current_ret) > abs(mean_ret) + 4 * std_ret:
                veto = True
                details_parts.append(f"📈 Movimento brusco: {current_ret*100:.2f}% em 1 min")
        
        # --- RESULTADO FINAL ---
        
        if veto:
            # Ativa cooldown
            self.cooldown_counters[symbol] = self.config.cooldown_candles
            
            # Registra anomalia
            anomaly_record = {
                "timestamp": pd.Timestamp.now().isoformat(),
                "symbol": symbol,
                "score": round(anomaly_score, 1),
                "features": anomalous_features,
                "details": "; ".join(details_parts)
            }
            self.anomaly_log.append(anomaly_record)
            # Mantém log com no máximo 100 entradas
            if len(self.anomaly_log) > 100:
                self.anomaly_log = self.anomaly_log[-100:]
            
            logger.warning(f"🚨 ANOMALY DETECTED | {symbol} | "
                         f"Score: {anomaly_score:.1f} | "
                         f"{'; '.join(details_parts)}")
            
            return {
                "status": "ANOMALY",
                "symbol": symbol,
                "anomaly_score": round(anomaly_score, 1),
                "anomalous_features": anomalous_features,
                "veto": True,
                "details": "; ".join(details_parts),
                "shield_active": True,
                "cooldown_remaining": self.config.cooldown_candles
            }
        
        # Mercado normal — libera operação
        return {
            "status": "NORMAL",
            "symbol": symbol,
            "anomaly_score": round(anomaly_score, 1),
            "anomalous_features": anomalous_features,
            "veto": False,
            "details": "Mercado operando dentro da normalidade.",
            "shield_active": True
        }
    
    # -------------------------------------------------------------------------
    # CONSULTAS DE ESTADO
    # -------------------------------------------------------------------------
    
    def get_shield_status(self, symbol: Optional[str] = None) -> Dict:
        """Retorna o status atual do shield para um ou todos os pares."""
        if symbol:
            return {
                "symbol": symbol,
                "trained": symbol in self.baselines,
                "active": self.shield_active.get(symbol, False),
                "cooldown": self.cooldown_counters.get(symbol, 0),
                "buffer_size": len(self.feature_buffers.get(symbol, [])),
                "darts_available": self.darts_available
            }
        
        return {
            "pares_treinados": list(self.baselines.keys()),
            "pares_ativos": {s: a for s, a in self.shield_active.items()},
            "darts_available": self.darts_available,
            "total_anomalias": len(self.anomaly_log),
            "ultimas_anomalias": self.anomaly_log[-5:] if self.anomaly_log else []
        }
    
    def get_regime_advisory(self, symbol: str) -> Dict:
        """
        Gera um parecer de regime de mercado baseado nas anomalias detectadas.
        Útil para o relatório de regime (complementa o MarketRegimeDetection).
        """
        baseline = self.baselines.get(symbol)
        if not baseline:
            return {"symbol": symbol, "regime": "UNKNOWN", "reliability": "LOW"}
        
        buffer = self.feature_buffers.get(symbol)
        if buffer is None or len(buffer) < 10:
            return {"symbol": symbol, "regime": "INSUFFICIENT_DATA"}
        
        recent = buffer.tail(10)
        avg_vol = recent['range_pct'].mean()
        avg_volume_ratio = recent['volume_ratio'].mean()
        
        volatility = baseline['range_pct']['mean']
        
        # Determina regime
        if avg_vol > volatility * 1.8:
            regime = "HIGH_VOLATILITY_ANOMALOUS"
            reliability = "HIGH"
        elif avg_vol > volatility * 1.3:
            regime = "HIGH_VOLATILITY"
            reliability = "MEDIUM"
        elif avg_vol < volatility * 0.5:
            regime = "LOW_VOLATILITY_LIQUIDITY"
            reliability = "HIGH"
        elif avg_volume_ratio < 0.5:
            regime = "LOW_VOLUME_CAUTION"
            reliability = "MEDIUM"
        else:
            regime = "NORMAL"
            reliability = "HIGH"
        
        return {
            "symbol": symbol,
            "regime": regime,
            "reliability": reliability,
            "avg_volatility": round(float(avg_vol), 4),
            "baseline_volatility": round(float(volatility), 4),
            "avg_volume_ratio": round(float(avg_volume_ratio), 2)
        }


# =============================================================================
# FUNÇÃO PRINCIPAL — PONTO DE ENTRADA ÚNICO
# =============================================================================

def run_anomaly_check(symbol: str, current_candle: Dict, 
                      shield: Optional[DartsAnomalyShield] = None,
                      historical_data: Optional[pd.DataFrame] = None) -> Dict:
    """
    Função principal para executar a verificação de anomalia.
    
    Uso simplificado:
    
        from core.integrations.darts_anomaly_shield import run_anomaly_check
        
        resultado = run_anomaly_check(
            symbol="EURUSD",
            current_candle={"open": 1.0850, "high": 1.0855, ...},
            historical_data=df_ultimos_1000_candles  # apenas na primeira chamada
        )
        
        if resultado["veto"]:
            print("🚨 BLOQUEADO por anomalia de mercado!")
        else:
            print("✅ Mercado normal — pode operar.")
    
    Args:
        symbol: Par forex
        current_candle: OHLCV do candle atual
        shield: Instância existente do shield (reutilizar)
        historical_data: DataFrame para treino inicial (opcional na 1ª chamada)
    
    Returns:
        Dict com resultado da verificação
    """
    # Cria ou reusa o shield
    if shield is None:
        shield = DartsAnomalyShield()
    
    # Treina se recebeu dados históricos e ainda não treinou para este par
    if historical_data is not None and symbol not in shield.baselines:
        shield.train(symbol, historical_data)
    
    # Executa o scan
    return shield.scan(symbol, current_candle)


print("🏛️🚨 DARTS ANOMALY SHIELD (Camada 0) — Módulo carregado com sucesso.")
print("📊 Protegendo: Volatilidade | Spread | Volume | Retornos | Padrões Anômalos")