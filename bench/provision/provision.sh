#!/bin/bash
# Provisionne la VM du banc : Mininet + Open vSwitch (natifs arm64).
#
# Pas de contrôleur SDN externe : ONOS 2.7 ne boote pas sur Apple Silicon
# (bundles natifs de boot sans variante aarch64 ; en x86_64/Rosetta le cache de
# bundles Felix échoue) et Ryu ne s'installe pas proprement sur Python 3.10
# (packaging cassé). Le banc applique donc les actions directement en règles
# OpenFlow sur Open vSwitch (le switch OpenFlow de référence) via ovs-ofctl :
# InferRouter tient le rôle de décideur northbound, la validation porte sur
# l'effet réel dans le plan de données.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y mininet openvswitch-switch python3 python3-pip iperf net-tools
systemctl enable --now openvswitch-switch
echo "Provision terminé (Mininet + Open vSwitch)."
