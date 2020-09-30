#!/bin/bash

CMD="docker run -u ${UID}:$(id -g) -w /tmp/conversion -v ${PWD}:/tmp/conversion --rm registry.gitlab.com/probocop/janus-gateway janus-pp-rec"

for STREAMNAME in $(ls *mjr); do
    STREAMNAME_BASE=$(basename "${STREAMNAME}" .mjr)
    if [[ ${STREAMNAME_BASE} =~ 'audio' ]]; then
        echo audio file: ${STREAMNAME}
        EXTENSION=opus
    else
        EXTENSION=webm
    fi
    ${CMD} "${STREAMNAME}" "${STREAMNAME_BASE}.${EXTENSION}"
done
