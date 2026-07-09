# Extract the archive
mkdir yapo_analysis
tar -xzf yapo.tar.gz -C yapo_analysis
cd yapo_analysis

# Check total size
du -sh .

# List all layers with sizes
for layer in */layer.tar; do
    size=$(du -h "$layer" | cut -f1)
    echo "$size - $layer"
done | sort -hr

# Find the largest layer
ls -lhS */layer.tar | head -5

# Examine the largest layer's contents
LARGEST=$(ls -S */layer.tar | head -1)
echo "Largest layer: $LARGEST"
tar -tvf "$LARGEST" | sort -k5 -hr | head -20
