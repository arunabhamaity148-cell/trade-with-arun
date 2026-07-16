"""Declarative concurrent experiment runner with reproducible persisted results."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from twa.config import Settings
from twa.logging import get_logger
from twa.models.types import Candle, coerce_timeframe
from twa.research.edge_validation import EdgeValidationFramework, ThresholdStrategy
from twa.research.feature_discovery import FeatureDiscoveryEngine
from twa.research.lab import ResearchLab, ResearchSession
from twa.research.utils import content_hash, ensure_research_dir

log = get_logger("research.experiment_runner")


class Experiment(BaseModel):
    name: str
    symbols: List[str]
    timeframe: str = "1h"
    lookback_bars: int = 400
    feature_set: List[str] = Field(default_factory=list)
    strategy: Dict[str, object] = Field(default_factory=dict)
    parameters: Dict[str, object] = Field(default_factory=dict)


class SymbolExperimentResult(BaseModel):
    symbol: str
    top_features: List[str] = Field(default_factory=list)
    validation: dict = Field(default_factory=dict)


class ExperimentResult(BaseModel):
    name: str
    config_hash: str
    saved_path: str
    results: List[SymbolExperimentResult] = Field(default_factory=list)


class ExperimentRunner:
    """Run and persist experiments without touching production parameters."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.lab = ResearchLab(settings)
        self.discovery = FeatureDiscoveryEngine()
        self.validation = EdgeValidationFramework()

    async def close(self) -> None:
        await self.lab.close()

    async def run_config_path(self, config_path: Path, candles_map: Optional[Dict[str, List[Candle]]] = None) -> ExperimentResult:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        experiment = Experiment.model_validate(payload)
        return await self.run(experiment, candles_map=candles_map)

    async def run(self, experiment: Experiment, candles_map: Optional[Dict[str, List[Candle]]] = None) -> ExperimentResult:
        session_results: List[SymbolExperimentResult] = []
        for symbol in experiment.symbols:
            session = await self.lab.load_session(
                symbol,
                experiment.timeframe,
                limit=experiment.lookback_bars,
                candles=(candles_map or {}).get(symbol),
            )
            session_results.append(self._run_one_symbol(session, experiment))
        payload = experiment.model_dump(mode="json")
        cfg_hash = content_hash(payload)
        out_dir = ensure_research_dir(self.settings, "experiments")
        out_path = out_dir / f"{cfg_hash}.json"
        result = ExperimentResult(
            name=experiment.name,
            config_hash=cfg_hash,
            saved_path=str(out_path),
            results=session_results,
        )
        out_path.write_text(
            json.dumps({"config": payload, "result": result.model_dump(mode="json")}, indent=2, default=str),
            encoding="utf-8",
        )
        log.info("research.experiment.saved", name=experiment.name, path=str(out_path))
        return result

    def _run_one_symbol(self, session: ResearchSession, experiment: Experiment) -> SymbolExperimentResult:
        report = self.discovery.discover(session)
        top_names = [row.name for row in report.rows[:5]]
        strategy = ThresholdStrategy(
            name=str(experiment.strategy.get("name", f"{experiment.name}_{session.symbol}")),
            feature_name=str(experiment.strategy.get("feature_name", experiment.parameters.get("feature_name", "log_return_16"))),
            threshold=float(experiment.strategy.get("threshold", experiment.parameters.get("threshold", 0.0))),
            direction=str(experiment.strategy.get("direction", experiment.parameters.get("direction", "above"))),
            trade_side=str(experiment.strategy.get("trade_side", experiment.parameters.get("trade_side", "long"))),
            horizon=int(experiment.strategy.get("horizon", experiment.parameters.get("horizon", 4))),
        )
        validation = self.validation.validate(session, strategy)
        return SymbolExperimentResult(
            symbol=session.symbol,
            top_features=top_names,
            validation=validation.model_dump(mode="json"),
        )
