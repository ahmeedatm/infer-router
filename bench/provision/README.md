# Banc Mininet + Open vSwitch (VM Lima)

Aucun contrôleur SDN externe. ONOS ne démarre pas sur Apple Silicon et Ryu ne
s'installe pas sur Python récent (constat du 2026-07-24), donc InferRouter joue
lui-même le rôle du décideur et les opérations sont posées directement sur OVS.

## Démarrer la VM

```bash
limactl start --name inferbench bench/provision/lima.yaml
limactl shell inferbench
```

## Vérifier le banc avant tout run

```bash
cd /opt/infer-router && sudo python3 -m bench.smoke
```

Attendu : `SMOKE OK: base forwarding works on diamond4`. Un échec signifie que
les règles de base du mode secure sont mal posées ; inutile de lancer le run
complet tant que ce test ne passe pas.

## Run complet

```bash
# 1. Sur le Mac, produire les plans (API OpenRouter) :
python experiments/run_realworld_validation.py

# 2. Dans la VM, rejouer sur le banc :
cd /opt/infer-router && sudo python3 -m bench.run_bench
cat experiments/results/realworld/realization_table.md
```

Compter 20 à 30 minutes pour 24 intents × 3 stratégies : chaque cas reconstruit
la topologie et certains checks lancent un iperf de 5 s.
