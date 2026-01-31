# Lens Loop (Aether Lens DevLoop)

# 1. Global Settings
# KINDクラスター名を許可
allow_k8s_contexts('kind-cluster1')

# 2. Image Build & Push
# 内部レジストリ registry.aether.internal を使用
# registry 引数を指定することで KIND へのロードではなくプッシュを強制
docker_build(
    'registry.aether.internal/aether-lens',
    context='.',
    dockerfile='Dockerfile',
    registry='registry.aether.internal',
    live_update=[
        # local -> container path mapping
        sync('./src/aether_lens', '/usr/local/lib/python3.11/site-packages/aether_lens'),
    ]
)

# 2. Kubernetes Deployment
k8s_yaml('deployment.yaml')

# 3. Resource Configuration
k8s_resource(
    'aether-vision-poc',
    port_forwards=3000, # test-runner (Browserless)
    labels=['lens-loop']
)

# 4. Local Resource for Dev Server (Optional, if running locally)
# local_resource(
#     'astro-dev',
#     cmd='cd ../app/public/docs && make dev',
#     deps=['../app/public/docs/starlight/src']
# )
