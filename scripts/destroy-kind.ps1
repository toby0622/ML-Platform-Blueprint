[CmdletBinding(SupportsShouldProcess)]
param([string]$ClusterName = "ml-platform")

$ErrorActionPreference = "Stop"
if (-not (Get-Command kind -ErrorAction SilentlyContinue)) {
    throw "Missing required tool: kind"
}

$clusters = @(kind get clusters)
if ($clusters -contains $ClusterName) {
    if ($PSCmdlet.ShouldProcess("kind cluster '$ClusterName'", "Delete")) {
        kind delete cluster --name $ClusterName
    }
} else {
    Write-Output "kind cluster $ClusterName does not exist; nothing to delete"
}
