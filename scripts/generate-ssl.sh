#!/bin/bash
# Generate self-signed SSL certificates for development/testing

set -e

CERT_DIR="docker/ssl"
DOMAIN="${1:-localhost}"
DAYS="${2:-365}"

echo "Generating SSL certificates for: $DOMAIN"
echo "Valid for: $DAYS days"
echo ""

# Create directory if it doesn't exist
mkdir -p "$CERT_DIR"

# Generate private key
echo "Generating private key..."
openssl genrsa -out "$CERT_DIR/key.pem" 2048

# Generate certificate signing request
echo "Generating certificate signing request..."
openssl req -new -key "$CERT_DIR/key.pem" -out "$CERT_DIR/cert.csr" \
    -subj "/C=US/ST=State/L=City/O=Organization/OU=IT/CN=$DOMAIN"

# Generate self-signed certificate
echo "Generating self-signed certificate..."
openssl x509 -req -days "$DAYS" \
    -in "$CERT_DIR/cert.csr" \
    -signkey "$CERT_DIR/key.pem" \
    -out "$CERT_DIR/cert.pem"

# Clean up CSR
rm "$CERT_DIR/cert.csr"

# Set permissions
chmod 600 "$CERT_DIR/key.pem"
chmod 644 "$CERT_DIR/cert.pem"

echo ""
echo "✓ SSL certificates generated successfully!"
echo ""
echo "Certificate: $CERT_DIR/cert.pem"
echo "Private Key: $CERT_DIR/key.pem"
echo ""
echo "⚠ WARNING: This is a self-signed certificate for development/testing only."
echo "⚠ For production, use a certificate from a trusted CA (e.g., Let's Encrypt)"
echo ""
echo "To trust this certificate locally:"
echo "  - macOS: sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain $CERT_DIR/cert.pem"
echo "  - Linux: sudo cp $CERT_DIR/cert.pem /usr/local/share/ca-certificates/ && sudo update-ca-certificates"
echo "  - Windows: Import cert.pem into 'Trusted Root Certification Authorities'"
echo ""
