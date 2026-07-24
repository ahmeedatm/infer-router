# Banc Mininet + ONOS (VM Lima)

## Démarrer la VM
```bash
limactl start --name inferbench bench/provision/lima.yaml
limactl shell inferbench
```

## Vérifier ONOS (dans la VM, après ~90 s)
```bash
curl -u karaf:karaf http://127.0.0.1:8181/onos/v1/applications | head
# Activer les apps si besoin :
ssh -p 8101 karaf@localhost   # pw: karaf
#   app activate org.onosproject.openflow
#   app activate org.onosproject.fwd
```

## Test de fumée Mininet sous contrôle ONOS
```bash
sudo mn --topo single,3 --mac --switch ovs,protocols=OpenFlow14 \
        --controller remote,ip=127.0.0.1 --test pingall
```
Attendu : `0% dropped`.

## Run complet (dans la VM)
```bash
# 1. (sur le Mac) produire les actions : python experiments/run_realworld_validation.py
# 2. (dans la VM) rejouer sur le banc :
cd /opt/infer-router && sudo python3 -m bench.run_bench
cat experiments/results/realworld/realization_table.md
```
