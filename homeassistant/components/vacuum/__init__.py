"""Support for vacuum cleaner robots (botvacs)."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from enum import IntFlag
from functools import partial
import logging
from typing import TYPE_CHECKING, Any, final

from propcache.api import cached_property
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (  # noqa: F401 # STATE_PAUSED/IDLE are API
    ATTR_BATTERY_LEVEL,
    ATTR_COMMAND,
    SERVICE_TOGGLE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.deprecation import (
    DeprecatedConstantEnum,
    all_with_deprecated_constants,
    check_if_deprecated_constant,
    dir_with_deprecated_constants,
)
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.helpers.entity_platform import EntityPlatform
from homeassistant.helpers.frame import ReportBehavior, report_usage
from homeassistant.helpers.icon import icon_for_battery_level
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import bind_hass
from homeassistant.util.hass_dict import HassKey

from .const import (  # noqa: F401
    _DEPRECATED_STATE_AUTO_EMPTYING,
    _DEPRECATED_STATE_CLEANING,
    _DEPRECATED_STATE_CLEANING_MOPS,
    _DEPRECATED_STATE_DOCKED,
    _DEPRECATED_STATE_DRYING_MOPS,
    _DEPRECATED_STATE_ERROR,
    _DEPRECATED_STATE_MOPPING,
    _DEPRECATED_STATE_RETURNING,
    _DEPRECATED_STATE_VACUUMING,
    _DEPRECATED_STATE_VACUUMING_AND_MOPPING,
    DEFAULT_CLEANING_MODES,
    DEFAULT_MOP_INTENSITIES,
    DOMAIN,
    VacuumActivity,
)

_LOGGER = logging.getLogger(__name__)

DATA_COMPONENT: HassKey[EntityComponent[StateVacuumEntity]] = HassKey(DOMAIN)
ENTITY_ID_FORMAT = DOMAIN + ".{}"
PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA
PLATFORM_SCHEMA_BASE = cv.PLATFORM_SCHEMA_BASE
SCAN_INTERVAL = timedelta(seconds=20)

ATTR_AUTO_EMPTY_STATUS = "auto_empty_status"
ATTR_BATTERY_ICON = "battery_icon"
ATTR_CLEANED_AREA = "cleaned_area"
ATTR_FAN_SPEED = "fan_speed"
ATTR_FAN_SPEED_LIST = "fan_speed_list"
ATTR_MOP_CLEANING_STATUS = "mop_cleaning_status"
ATTR_MOP_DRYING_STATUS = "mop_drying_status"
ATTR_PARAMS = "params"
ATTR_STATUS = "status"
ATTR_CLEANING_MODE = "cleaning_mode"
ATTR_CLEANING_MODE_LIST = "cleaning_mode_list"
ATTR_MOP_INTENSITY = "mop_intensity"
ATTR_CURRENT_MOP_INTENSITY = "mop_intensity"
ATTR_MOP_INTENSITY_LIST = "mop_intensity_list"
ATTR_EMPTY_REQUIRED = "empty_required"

SERVICE_CLEAN_SPOT = "clean_spot"
SERVICE_LOCATE = "locate"
SERVICE_RETURN_TO_BASE = "return_to_base"
SERVICE_SEND_COMMAND = "send_command"
SERVICE_SET_FAN_SPEED = "set_fan_speed"
SERVICE_SET_CLEANING_MODE = "set_cleaning_mode"
SERVICE_SET_MOP_INTENSITY = "set_mop_intensity"
SERVICE_START_AUTO_EMPTY = "start_auto_empty"
SERVICE_START_MOP_DRYING = "start_mop_drying"
SERVICE_START_MOP_CLEANING = "start_mop_cleaning"
SERVICE_START_PAUSE = "start_pause"
SERVICE_START = "start"
SERVICE_PAUSE = "pause"
SERVICE_STOP = "stop"

DEFAULT_NAME = "Vacuum cleaner robot"

# These STATE_* constants are deprecated as of Home Assistant 2025.1.
# Please use the VacuumActivity enum instead.
_DEPRECATED_STATE_IDLE = DeprecatedConstantEnum(VacuumActivity.IDLE, "2026.1")
_DEPRECATED_STATE_PAUSED = DeprecatedConstantEnum(VacuumActivity.PAUSED, "2026.1")

_BATTERY_DEPRECATION_IGNORED_PLATFORMS = (
    "mqtt",
    "template",
)


class VacuumEntityFeature(IntFlag):
    """Supported features of the vacuum entity."""

    AUTO_EMPTY = 65536
    BATTERY = 64
    CLEAN_SPOT = 1024
    CLEANING_MODE = 262144
    DRYING_MOP = 131072
    FAN_SPEED = 32
    LOCATE = 512
    MAP = 2048
    MOP = 16384
    MOP_CLEANING = 1048576
    MOP_INTENSITY = 524288
    MOP_VACUUM = 32768
    PAUSE = 4
    RETURN_HOME = 16
    SEND_COMMAND = 256
    START = 8192
    STATE = 4096  # Must be set by vacuum platforms derived from StateVacuumEntity
    STATUS = 128  # Deprecated, not supported by StateVacuumEntity
    STOP = 8
    TURN_OFF = 2  # Deprecated, not supported by StateVacuumEntity
    TURN_ON = 1  # Deprecated, not supported by StateVacuumEntity



# mypy: disallow-any-generics


@bind_hass
def is_on(hass: HomeAssistant, entity_id: str) -> bool:
    """Return if the vacuum is on based on the statemachine."""
    return hass.states.is_state(entity_id, STATE_ON)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the vacuum component."""
    component = hass.data[DATA_COMPONENT] = EntityComponent[StateVacuumEntity](
        _LOGGER, DOMAIN, hass, SCAN_INTERVAL
    )

    await component.async_setup(config)

    component.async_register_entity_service(
        SERVICE_START,
        None,
        "async_start",
        [VacuumEntityFeature.START],
    )
    component.async_register_entity_service(
        SERVICE_PAUSE,
        None,
        "async_pause",
        [VacuumEntityFeature.PAUSE],
    )
    component.async_register_entity_service(
        SERVICE_RETURN_TO_BASE,
        None,
        "async_return_to_base",
        [VacuumEntityFeature.RETURN_HOME],
    )
    component.async_register_entity_service(
        SERVICE_CLEAN_SPOT,
        None,
        "async_clean_spot",
        [VacuumEntityFeature.CLEAN_SPOT],
    )
    component.async_register_entity_service(
        SERVICE_LOCATE,
        None,
        "async_locate",
        [VacuumEntityFeature.LOCATE],
    )
    component.async_register_entity_service(
        SERVICE_STOP,
        None,
        "async_stop",
        [VacuumEntityFeature.STOP],
    )
    component.async_register_entity_service(
        SERVICE_SET_FAN_SPEED,
        {vol.Required(ATTR_FAN_SPEED): cv.string},
        "async_set_fan_speed",
        [VacuumEntityFeature.FAN_SPEED],
    )
    component.async_register_entity_service(
        SERVICE_SET_CLEANING_MODE,
        {vol.Required(ATTR_CLEANING_MODE): cv.string},
        "async_set_cleaning_mode",
        [VacuumEntityFeature.CLEANING_MODE],
    )
    component.async_register_entity_service(
        SERVICE_SET_MOP_INTENSITY,
        {vol.Required(ATTR_MOP_INTENSITY): cv.string},
        "async_set_mop_intensity",
        [VacuumEntityFeature.MOP_INTENSITY],
    )
    component.async_register_entity_service(
        SERVICE_SEND_COMMAND,
        {
            vol.Required(ATTR_COMMAND): cv.string,
            vol.Optional(ATTR_PARAMS): vol.Any(dict, cv.ensure_list),
        },
        "async_send_command",
        [VacuumEntityFeature.SEND_COMMAND],
    )
    component.async_register_entity_service(
        SERVICE_START_AUTO_EMPTY,
        None,
        "async_start_auto_empty",
        [VacuumEntityFeature.AUTO_EMPTY],
    )
    component.async_register_entity_service(
        SERVICE_START_MOP_DRYING,
        None,
        "async_start_mop_drying",
        [VacuumEntityFeature.DRYING_MOP],
    )
    component.async_register_entity_service(
        SERVICE_START_MOP_CLEANING,
        None,
        "async_start_mop_cleaning",
        [VacuumEntityFeature.MOP_CLEANING],
    )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry."""
    return await hass.data[DATA_COMPONENT].async_setup_entry(entry)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.data[DATA_COMPONENT].async_unload_entry(entry)


class StateVacuumEntityDescription(EntityDescription, frozen_or_thawed=True):
    """A class that describes vacuum entities."""


STATE_VACUUM_CACHED_PROPERTIES_WITH_ATTR_ = {
    "supported_features",
    "auto_empty_count",
    "auto_empty_status",
    "battery_level",
    "battery_icon",
    "fan_speed",
    "fan_speed_list",
    "cleaning_mode",
    "cleaning_modes",
    "mop_intensity",
    "mop_intensities",
    "mop_cleaning_status",
    "mop_drying_status",
    "activity",
}


class StateVacuumEntity(
    Entity, cached_properties=STATE_VACUUM_CACHED_PROPERTIES_WITH_ATTR_
):
    """Representation of a vacuum cleaner robot that supports states."""

    entity_description: StateVacuumEntityDescription

    _entity_component_unrecorded_attributes = frozenset(
        {ATTR_FAN_SPEED_LIST, ATTR_CLEANING_MODE_LIST, ATTR_MOP_INTENSITY_LIST}
    )

    _attr_auto_empty_count: int | None = None
    _attr_auto_empty_status: str | None = None
    _attr_battery_icon: str
    _attr_battery_level: int | None = None
    _attr_fan_speed: str | None = None
    _attr_fan_speed_list: list[str]
    _attr_cleaning_mode: str | None = None
    _attr_cleaning_modes_list: list[str] = DEFAULT_CLEANING_MODES
    _attr_mop_intensity: str | None = None
    _attr_mop_intensity_list: list[str] = DEFAULT_MOP_INTENSITIES
    _attr_mop_cleaning_status: str | None = None
    _attr_mop_drying_status: str | None = None
    _attr_empty_required: bool | None = None
    _attr_activity: VacuumActivity | None = None
    _attr_supported_features: VacuumEntityFeature = VacuumEntityFeature(0)

    __vacuum_legacy_state: bool = False
    __vacuum_legacy_battery_level: bool = False
    __vacuum_legacy_battery_icon: bool = False
    __vacuum_legacy_battery_feature: bool = False

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Post initialisation processing."""
        super().__init_subclass__(**kwargs)
        if any(method in cls.__dict__ for method in ("_attr_state", "state")):
            # Integrations should use the 'activity' property instead of
            # setting the state directly.
            cls.__vacuum_legacy_state = True
        if any(
            method in cls.__dict__
            for method in ("_attr_battery_level", "battery_level")
        ):
            # Integrations should use a separate battery sensor.
            cls.__vacuum_legacy_battery_level = True
        if any(
            method in cls.__dict__ for method in ("_attr_battery_icon", "battery_icon")
        ):
            # Integrations should use a separate battery sensor.
            cls.__vacuum_legacy_battery_icon = True

    def __setattr__(self, name: str, value: Any) -> None:
        """Set attribute.

        Deprecation warning if setting state, battery icon or battery level
        attributes directly unless already reported.
        """
        if name == "_attr_state":
            self._report_deprecated_activity_handling()
        if name in {"_attr_battery_level", "_attr_battery_icon"}:
            self._report_deprecated_battery_properties(name[6:])
        return super().__setattr__(name, value)

    @callback
    def add_to_platform_start(
        self,
        hass: HomeAssistant,
        platform: EntityPlatform,
        parallel_updates: asyncio.Semaphore | None,
    ) -> None:
        """Start adding an entity to a platform."""
        super().add_to_platform_start(hass, platform, parallel_updates)
        if self.__vacuum_legacy_state:
            self._report_deprecated_activity_handling()
        if self.__vacuum_legacy_battery_level:
            self._report_deprecated_battery_properties("battery_level")
        if self.__vacuum_legacy_battery_icon:
            self._report_deprecated_battery_properties("battery_icon")

    @callback
    def _report_deprecated_activity_handling(self) -> None:
        """Report on deprecated handling of vacuum state.

        Integrations should implement activity instead of using state directly.
        """
        report_usage(
            "is setting state directly."
            f" Entity {self.entity_id} ({type(self)}) should implement the 'activity'"
            " property and return its state using the VacuumActivity enum",
            core_integration_behavior=ReportBehavior.ERROR,
            custom_integration_behavior=ReportBehavior.LOG,
            breaks_in_ha_version="2026.1",
            integration_domain=self.platform.platform_name if self.platform else None,
            exclude_integrations={DOMAIN},
        )

    @callback
    def _report_deprecated_battery_properties(self, property: str) -> None:
        """Report on deprecated use of battery properties.

        Integrations should implement a sensor instead.
        """
        if (
            self.platform
            and self.platform.platform_name
            not in _BATTERY_DEPRECATION_IGNORED_PLATFORMS
        ):
            # Don't report usage until after entity added to hass, after init
            report_usage(
                f"is setting the {property} which has been deprecated."
                f" Integration {self.platform.platform_name} should implement a sensor"
                " instead with a correct device class and link it to the same device",
                core_integration_behavior=ReportBehavior.IGNORE,
                custom_integration_behavior=ReportBehavior.LOG,
                breaks_in_ha_version="2026.8",
                integration_domain=self.platform.platform_name,
                exclude_integrations={DOMAIN},
            )

    @callback
    def _report_deprecated_battery_feature(self) -> None:
        """Report on deprecated use of battery supported features.

        Integrations should remove the battery supported feature when migrating
        battery level and icon to a sensor.
        """
        if (
            self.platform
            and self.platform.platform_name
            not in _BATTERY_DEPRECATION_IGNORED_PLATFORMS
        ):
            # Don't report usage until after entity added to hass, after init
            report_usage(
                f"is setting the battery supported feature which has been deprecated."
                f" Integration {self.platform.platform_name} should remove this as part of migrating"
                " the battery level and icon to a sensor",
                core_behavior=ReportBehavior.LOG,
                core_integration_behavior=ReportBehavior.IGNORE,
                custom_integration_behavior=ReportBehavior.LOG,
                breaks_in_ha_version="2026.8",
                integration_domain=self.platform.platform_name,
                exclude_integrations={DOMAIN},
            )

    @cached_property
    def battery_level(self) -> int | None:
        """Return the battery level of the vacuum cleaner."""
        return self._attr_battery_level

    @property
    def battery_icon(self) -> str:
        """Return the battery icon for the vacuum cleaner."""
        charging = bool(self.activity == VacuumActivity.DOCKED)

        return icon_for_battery_level(
            battery_level=self.battery_level, charging=charging
        )

    @property
    def capability_attributes(self) -> dict[str, Any] | None:
        """Return capability attributes."""
        data: dict[str, Any] = {}
        supported_features = self.supported_features

        if VacuumEntityFeature.FAN_SPEED in supported_features:
            data[ATTR_FAN_SPEED_LIST] = self.fan_speed_list

        if VacuumEntityFeature.CLEANING_MODE in supported_features:
            data[ATTR_CLEANING_MODE_LIST] = self.cleaning_modes_list

        if VacuumEntityFeature.MOP_INTENSITY in supported_features:
            data[ATTR_MOP_INTENSITY_LIST] = self.mop_intensity_list

        return data if data else None

    @cached_property
    def fan_speed(self) -> str | None:
        """Return the fan speed of the vacuum cleaner."""
        return self._attr_fan_speed

    @cached_property
    def fan_speed_list(self) -> list[str]:
        """Get the list of available fan speed steps of the vacuum cleaner."""
        return self._attr_fan_speed_list

    @cached_property
    def cleaning_mode(self) -> str | None:
        """Return the cleaning mode of the vacuum cleaner."""
        return self._attr_cleaning_mode

    @cached_property
    def cleaning_modes_list(self) -> list[str]:
        """Get the list of available cleaning modes of the vacuum cleaner."""
        return self._attr_cleaning_modes_list

    @cached_property
    def mop_intensity(self) -> str | None:
        """Return the mop intensity of the vacuum cleaner."""
        return self._attr_mop_intensity

    @cached_property
    def mop_intensity_list(self) -> list[str]:
        """Get the list of available mop intensity levels of the vacuum cleaner."""
        return self._attr_mop_intensity_list

    @cached_property
    def auto_empty_status(self) -> str | None:
        """Return the auto empty status of the docking station."""
        return self._attr_auto_empty_status

    @cached_property
    def mop_drying_status(self) -> str | None:
        """Return the mop drying status of the docking station."""
        return self._attr_mop_drying_status

    @cached_property
    def mop_cleaning_status(self) -> str | None:
        """Return the mop cleaning status of the docking station."""
        return self._attr_mop_cleaning_status

    @cached_property
    def is_dock_empty_required(self) -> bool:
        """Required base dust collector replacement"""
        if self._attr_empty_required:
            return True
        return False

    @property
    def state_attributes(self) -> dict[str, Any]:
        """Return the state attributes of the vacuum cleaner."""
        data: dict[str, Any] = {}
        supported_features = self.supported_features

        if VacuumEntityFeature.BATTERY in supported_features:
            if self.__vacuum_legacy_battery_feature is False:
                self._report_deprecated_battery_feature()
                self.__vacuum_legacy_battery_feature = True
            data[ATTR_BATTERY_LEVEL] = self.battery_level
            data[ATTR_BATTERY_ICON] = self.battery_icon

        if VacuumEntityFeature.FAN_SPEED in supported_features:
            data[ATTR_FAN_SPEED] = self.fan_speed

        if VacuumEntityFeature.CLEANING_MODE in supported_features:
            data[ATTR_CLEANING_MODE] = self.cleaning_mode

        if VacuumEntityFeature.MOP_INTENSITY in supported_features:
            data[ATTR_CURRENT_MOP_INTENSITY] = self.mop_intensity

        if VacuumEntityFeature.AUTO_EMPTY in supported_features:
            data[ATTR_AUTO_EMPTY_STATUS] = self.auto_empty_status

        if VacuumEntityFeature.DRYING_MOP in supported_features:
            data[ATTR_MOP_DRYING_STATUS] = self.mop_drying_status

        if VacuumEntityFeature.MOP_CLEANING in supported_features:
            data[ATTR_MOP_CLEANING_STATUS] = self.mop_cleaning_status

        return data

    @final
    @property
    def state(self) -> str | None:
        """Return the state of the vacuum cleaner."""
        if (activity := self.activity) is not None:
            return activity
        if self._attr_state is not None:
            # Backwards compatibility for integrations that set state directly
            # Should be removed in 2026.1
            if TYPE_CHECKING:
                assert isinstance(self._attr_state, str)
            return self._attr_state
        return None

    @cached_property
    def activity(self) -> VacuumActivity | None:
        """Return the current vacuum activity.

        Integrations should overwrite this or use the '_attr_activity'
        attribute to set the vacuum activity using the 'VacuumActivity' enum.
        """
        return self._attr_activity

    @cached_property
    def supported_features(self) -> VacuumEntityFeature:
        """Flag vacuum cleaner features that are supported."""
        return self._attr_supported_features

    def stop(self, **kwargs: Any) -> None:
        """Stop the vacuum cleaner."""
        raise NotImplementedError

    async def async_stop(self, **kwargs: Any) -> None:
        """Stop the vacuum cleaner.

        This method must be run in the event loop.
        """
        await self.hass.async_add_executor_job(partial(self.stop, **kwargs))

    def return_to_base(self, **kwargs: Any) -> None:
        """Set the vacuum cleaner to return to the dock."""
        raise NotImplementedError

    async def async_return_to_base(self, **kwargs: Any) -> None:
        """Set the vacuum cleaner to return to the dock.

        This method must be run in the event loop.
        """
        await self.hass.async_add_executor_job(partial(self.return_to_base, **kwargs))

    def clean_spot(self, **kwargs: Any) -> None:
        """Perform a spot clean-up."""
        raise NotImplementedError

    async def async_clean_spot(self, **kwargs: Any) -> None:
        """Perform a spot clean-up.

        This method must be run in the event loop.
        """
        await self.hass.async_add_executor_job(partial(self.clean_spot, **kwargs))

    def locate(self, **kwargs: Any) -> None:
        """Locate the vacuum cleaner."""
        raise NotImplementedError

    async def async_locate(self, **kwargs: Any) -> None:
        """Locate the vacuum cleaner.

        This method must be run in the event loop.
        """
        await self.hass.async_add_executor_job(partial(self.locate, **kwargs))

    def set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        """Set fan speed."""
        raise NotImplementedError

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        """Set fan speed.

        This method must be run in the event loop.
        """
        await self.hass.async_add_executor_job(
            partial(self.set_fan_speed, fan_speed, **kwargs)
        )

    def set_cleaning_mode(self, cleaning_mode: str, **kwargs: Any) -> None:
        """Set cleaning mode."""
        raise NotImplementedError

    async def async_set_cleaning_mode(self, cleaning_mode: str, **kwargs: Any) -> None:
        """Set cleaning mode.

        This method must be run in the event loop.
        """
        await self.hass.async_add_executor_job(
            partial(self.set_cleaning_mode, cleaning_mode, **kwargs)
        )

    def set_mop_intensity(self, mop_intensity: str, **kwargs: Any) -> None:
        """Set mop intensity."""
        raise NotImplementedError

    async def async_set_mop_intensity(self, mop_intensity: str, **kwargs: Any) -> None:
        """Set mop intensity.

        This method must be run in the event loop.
        """
        await self.hass.async_add_executor_job(
            partial(self.set_mop_intensity, mop_intensity, **kwargs)
        )

    def send_command(
        self,
        command: str,
        params: dict[str, Any] | list[Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Send a command to a vacuum cleaner."""
        raise NotImplementedError

    async def async_send_command(
        self,
        command: str,
        params: dict[str, Any] | list[Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Send a command to a vacuum cleaner.

        This method must be run in the event loop.
        """
        await self.hass.async_add_executor_job(
            partial(self.send_command, command, params=params, **kwargs)
        )

    def start(self) -> None:
        """Start or resume the cleaning task."""
        raise NotImplementedError

    async def async_start(self) -> None:
        """Start or resume the cleaning task.

        This method must be run in the event loop.
        """
        await self.hass.async_add_executor_job(self.start)

    def pause(self) -> None:
        """Pause the cleaning task."""
        raise NotImplementedError

    async def async_pause(self) -> None:
        """Pause the cleaning task.

        This method must be run in the event loop.
        """
        await self.hass.async_add_executor_job(self.pause)

    def start_auto_empty(self) -> None:
        """Start auto-emptying the dustbin at the docking station."""
        raise NotImplementedError

    async def async_start_auto_empty(self) -> None:
        """Start auto-emptying the dustbin at the docking station.

        This method must be run in the event loop.
        """
        await self.hass.async_add_executor_job(self.start_auto_empty)

    def start_mop_drying(self) -> None:
        """Start drying the mop at the docking station."""
        raise NotImplementedError

    async def async_start_mop_drying(self) -> None:
        """Start drying the mop at the docking station.

        This method must be run in the event loop.
        """
        await self.hass.async_add_executor_job(self.start_mop_drying)

    def start_mop_cleaning(self) -> None:
        """Start cleaning the mop at the docking station."""
        raise NotImplementedError

    async def async_start_mop_cleaning(self) -> None:
        """Start cleaning the mop at the docking station.

        This method must be run in the event loop.
        """
        await self.hass.async_add_executor_job(self.start_mop_cleaning)


# As we import deprecated constants from the const module, we need to add these two functions
# otherwise this module will be logged for using deprecated constants and not the custom component
# These can be removed if no deprecated constant are in this module anymore
__getattr__ = partial(check_if_deprecated_constant, module_globals=globals())
__dir__ = partial(
    dir_with_deprecated_constants, module_globals_keys=[*globals().keys()]
)
__all__ = all_with_deprecated_constants(globals())
