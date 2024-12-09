try:
    from .const import (  # isort:skip
        __nameMyEnedis__,
    )

except ImportError:
    from const import (  # type: ignore[no-redef]
        __nameMyEnedis__,
    )

import logging

log = logging.getLogger(__nameMyEnedis__)


def okDataControl(
    clefFunction,
    dataControl,
    dateDeb,
    dateFin,
):
    log.debug("--okDataControl--")
    log.debug(f"--okDataControl / clefFunction : {clefFunction}")
    log.debug(
        "--okDataControl / deb : {} / {}".format(dataControl.get("deb", None), dateDeb)
    )
    log.debug(
        "--okDataControl / fin : {} / {}".format(dataControl.get("fin", None), dateFin)
    )
    log.debug("--okDataControl / callok : %s ", (dataControl.get("callok", True)))
    deb = dataControl.get("deb", None)
    fin = dataControl.get("fin", None)
    callOk = dataControl.get("callok", True)
    if callOk is None:
        callOk = True
    response = deb == dateDeb and fin == dateFin and callOk
    log.debug(f"--okDataControl / response : {response} ")
    return response


def getInformationDataControl(dataControl):
    return (
        dataControl.get("deb", None),
        dataControl.get("fin", None),
        dataControl.get("callok", None),
    )
