"""
Signal validation system - ensures all signals are factually correct
Non-negotiable truth guards before signals contribute to scores
"""
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from models.schemas import ValidatedSignal, SignalValidationStatus, DataSource


class SignalValidator:
    """Validates signals with boolean checks before they contribute to scores"""
    
    @staticmethod
    def validate_cpi_trend(
        current_value: float,
        previous_value: float,
        data_source: DataSource
    ) -> ValidatedSignal:
        """Validate CPI trend signal"""
        trend_direction = "up" if current_value > previous_value else "down" if current_value < previous_value else "flat"
        change_pct = ((current_value - previous_value) / previous_value) * 100 if previous_value > 0 else 0
        
        # Validation: Must have meaningful change (>0.1%) to claim trend
        is_valid = abs(change_pct) >= 0.1
        
        signal_name = f"CPI MoM {'falling' if trend_direction == 'down' else 'rising' if trend_direction == 'up' else 'flat'}"
        
        return ValidatedSignal(
            name=signal_name,
            value=current_value,
            previous_value=previous_value,
            trend_direction=trend_direction,
            validation_status=SignalValidationStatus.VALIDATED if is_valid else SignalValidationStatus.NEUTRALIZED,
            validation_check=f"abs(change_pct) >= 0.1% (actual: {change_pct:.2f}%)",
            validation_result=is_valid,
            score_contribution=20.0 if is_valid and trend_direction == "down" else 0.0 if is_valid and trend_direction == "up" else 10.0,
            data_source=data_source,
            notes=None if is_valid else "Change too small to claim trend - neutralized"
        )
    
    @staticmethod
    def validate_btc_above_200dma(
        btc_price: float,
        btc_200dma: float,
        data_source: DataSource
    ) -> ValidatedSignal:
        """Validate BTC above 200DMA signal"""
        is_above = btc_price > btc_200dma
        distance_pct = ((btc_price - btc_200dma) / btc_200dma) * 100 if btc_200dma > 0 else 0
        
        return ValidatedSignal(
            name="BTC above 200 DMA",
            value=btc_price,
            previous_value=btc_200dma,
            trend_direction="up" if is_above else "down",
            validation_status=SignalValidationStatus.VALIDATED if is_above else SignalValidationStatus.NEUTRALIZED,
            validation_check=f"btc_price ({btc_price}) > btc_200dma ({btc_200dma})",
            validation_result=is_above,
            score_contribution=15.0 if is_above else 0.0,
            data_source=data_source,
            notes=None if is_above else f"Condition not met - BTC is {abs(distance_pct):.2f}% below 200DMA - neutralized"
        )
    
    @staticmethod
    def validate_dxy_trend(
        current_price: float,
        week_ago_price: float,
        data_source: DataSource
    ) -> ValidatedSignal:
        """Validate DXY trend signal"""
        change_pct = ((current_price - week_ago_price) / week_ago_price) * 100 if week_ago_price > 0 else 0
        trend_direction = "down" if change_pct < -0.5 else "up" if change_pct > 0.5 else "flat"
        
        # Validation: Must have >0.5% change to claim trend
        is_valid = abs(change_pct) >= 0.5
        
        signal_name = f"DXY {'weakening' if trend_direction == 'down' else 'strengthening' if trend_direction == 'up' else 'stable'} 7D trend"
        
        return ValidatedSignal(
            name=signal_name,
            value=current_price,
            previous_value=week_ago_price,
            trend_direction=trend_direction,
            validation_status=SignalValidationStatus.VALIDATED if is_valid else SignalValidationStatus.NEUTRALIZED,
            validation_check=f"abs(change_pct) >= 0.5% (actual: {change_pct:.2f}%)",
            validation_result=is_valid,
            score_contribution=15.0 if is_valid and trend_direction == "down" else 0.0 if is_valid and trend_direction == "up" else 5.0,
            data_source=data_source,
            notes=None if is_valid else "Change too small to claim trend - neutralized"
        )
    
    @staticmethod
    def validate_yield_trend(
        current_yield: float,
        previous_yield: float,
        data_source: DataSource
    ) -> ValidatedSignal:
        """Validate yield trend signal"""
        change_bps = (current_yield - previous_yield) * 100  # Convert to basis points
        trend_direction = "down" if change_bps < -5 else "up" if change_bps > 5 else "flat"
        
        # Validation: Must have >5bps change to claim trend
        is_valid = abs(change_bps) >= 5
        
        signal_name = f"10Y yield {'falling' if trend_direction == 'down' else 'rising' if trend_direction == 'up' else 'stable'}"
        
        return ValidatedSignal(
            name=signal_name,
            value=current_yield,
            previous_value=previous_yield,
            trend_direction=trend_direction,
            validation_status=SignalValidationStatus.VALIDATED if is_valid else SignalValidationStatus.NEUTRALIZED,
            validation_check=f"abs(change_bps) >= 5bps (actual: {change_bps:.1f}bps)",
            validation_result=is_valid,
            score_contribution=15.0 if is_valid and trend_direction == "down" else 0.0 if is_valid and trend_direction == "up" else 5.0,
            data_source=data_source,
            notes=None if is_valid else "Change too small to claim trend - neutralized"
        )
    
    @staticmethod
    def validate_vix_level(
        vix_value: float,
        data_source: DataSource
    ) -> ValidatedSignal:
        """Validate VIX level signal.

        VIX > 30 = extreme fear. A bullish thesis cannot coexist with extreme fear —
        the signal is INVALIDATED (not just scored low) to force an explicit override.
        """
        if vix_value < 15:
            level = "low fear"
            score_contrib = 10.0
            status = SignalValidationStatus.VALIDATED
            valid_result = True
            notes = None
        elif vix_value <= 20:
            level = "moderate fear"
            score_contrib = 5.0
            status = SignalValidationStatus.VALIDATED
            valid_result = True
            notes = None
        elif vix_value <= 30:
            level = "elevated fear"
            score_contrib = 0.0
            status = SignalValidationStatus.VALIDATED
            valid_result = True
            notes = None
        else:
            level = "extreme fear"
            score_contrib = 0.0
            status = SignalValidationStatus.INVALIDATED
            valid_result = False
            notes = f"VIX {vix_value:.1f} > 30: extreme market fear — bullish bias invalidated"

        return ValidatedSignal(
            name=f"VIX at {vix_value:.1f} ({level})",
            value=vix_value,
            previous_value=None,
            trend_direction=None,
            validation_status=status,
            validation_check=f"VIX <= 30 for VALIDATED (actual: {vix_value:.1f})",
            validation_result=valid_result,
            score_contribution=score_contrib,
            data_source=data_source,
            notes=notes,
        )
    
    @staticmethod
    def validate_stablecoin_flow(
        current_cap: float,
        week_ago_cap: float,
        data_source: DataSource
    ) -> ValidatedSignal:
        """Validate stablecoin flow signal.

        Stablecoin outflow (capital leaving the crypto ecosystem) is bearish
        and INVALIDATES a bullish thesis. Inflow is a positive accumulation signal.
        """
        change_pct = ((current_cap - week_ago_cap) / week_ago_cap) * 100 if week_ago_cap > 0 else 0
        is_inflow = change_pct > 0.5
        is_outflow = change_pct < -0.5

        if is_inflow:
            signal_name = "Stablecoin inflow (accumulation signal)"
            score_contrib = 12.0
            trend = "up"
            status = SignalValidationStatus.VALIDATED
            valid_result = True
            notes = None
        elif is_outflow:
            signal_name = "Stablecoin outflow (capital leaving crypto)"
            score_contrib = 0.0
            trend = "down"
            status = SignalValidationStatus.INVALIDATED
            valid_result = False
            notes = f"change={change_pct:.2f}%: stablecoin outflow invalidates bullish accumulation thesis"
        else:
            signal_name = "Stablecoin supply stable"
            score_contrib = 5.0
            trend = "flat"
            status = SignalValidationStatus.VALIDATED
            valid_result = True
            notes = None

        return ValidatedSignal(
            name=signal_name,
            value=current_cap,
            previous_value=week_ago_cap,
            trend_direction=trend,
            validation_status=status,
            validation_check=f"change_pct={change_pct:.2f}% (INVALIDATED if < -0.5%)",
            validation_result=valid_result,
            score_contribution=score_contrib,
            data_source=data_source,
            notes=notes,
        )
    
    @staticmethod
    def check_data_freshness(data_as_of: datetime, max_stale_hours: float = 168) -> Tuple[bool, float]:
        """
        Check if data is fresh enough
        
        Args:
            data_as_of: When the data point is from
            max_stale_hours: Maximum hours old before considered stale (default 7 days)
        
        Returns:
            (is_fresh, hours_old)
        """
        hours_old = (datetime.now() - data_as_of).total_seconds() / 3600
        is_fresh = hours_old <= max_stale_hours
        return is_fresh, hours_old
    
    @staticmethod
    def create_data_source(
        name: str,
        series_id: Optional[str] = None,
        url: Optional[str] = None,
        data_as_of: Optional[datetime] = None
    ) -> DataSource:
        """Create a DataSource with freshness calculation"""
        if data_as_of is None:
            data_as_of = datetime.now()
        
        freshness_hours = (datetime.now() - data_as_of).total_seconds() / 3600
        
        return DataSource(
            name=name,
            series_id=series_id,
            url=url,
            last_updated=datetime.now(),
            data_as_of=data_as_of,
            freshness_hours=freshness_hours
        )

