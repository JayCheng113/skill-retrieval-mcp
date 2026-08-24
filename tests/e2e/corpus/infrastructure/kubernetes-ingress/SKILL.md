---
name: kubernetes-ingress
description: Expose a service running inside a Kubernetes cluster to traffic from outside the cluster.
category: infrastructure
tags: [kubernetes, ingress, networking, tls]
---

# Getting external traffic into a cluster

A `Service` of type `ClusterIP` is only reachable from inside the cluster. Three
ways out, in increasing order of control:

`NodePort` opens the same high port on every node. Cheap, but the port range is
constrained and you still need something in front to load balance across nodes.

`LoadBalancer` asks the cloud provider for one address per service. Simple, and
expensive once you have more than a handful of services.

`Ingress` puts one HTTP router in front of many services and routes by host and
path. It needs an ingress controller actually running in the cluster — the
`Ingress` object on its own does nothing, which is the most common reason a
freshly applied manifest silently never receives traffic.

Terminate TLS at the ingress and keep the certificate in a `Secret` the controller
can read; a certificate mounted into the workload pod instead will not be used.
