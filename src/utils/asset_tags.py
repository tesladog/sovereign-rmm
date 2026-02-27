"""
Asset Tag Generator - Creates both standard and compact labels
"""
from PIL import Image, ImageDraw, ImageFont
import qrcode
import barcode
from barcode.writer import ImageWriter
from io import BytesIO
import os


class AssetTagGenerator:
    """Generates asset tags in various sizes"""
    
    # Standard sizes (current)
    SIZE_LARGE = (200, 80)  # For laptops, desktops
    
    # Compact sizes (new)
    SIZE_COMPACT = (100, 40)  # For HDDs/SSDs
    SIZE_MINI = (75, 30)      # For small SSDs
    
    def __init__(self):
        # Try to load font, fallback to default
        try:
            self.font_large = ImageFont.truetype("arial.ttf", 16)
            self.font_medium = ImageFont.truetype("arial.ttf", 12)
            self.font_small = ImageFont.truetype("arial.ttf", 8)
            self.font_compact = ImageFont.truetype("arialbd.ttf", 10)  # Bold
        except:
            self.font_large = ImageFont.load_default()
            self.font_medium = ImageFont.load_default()
            self.font_small = ImageFont.load_default()
            self.font_compact = ImageFont.load_default()
    
    def generate_qr_code(self, data, size=100):
        """Generate QR code"""
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=1,
        )
        qr.add_data(data)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        img = img.resize((size, size), Image.Resampling.LANCZOS)
        
        return img
    
    def generate_barcode(self, data, width=200, height=60):
        """Generate Code128 barcode"""
        # Create barcode
        CODE128 = barcode.get_barcode_class('code128')
        
        # Use BytesIO to get image without saving to file
        buffer = BytesIO()
        writer = ImageWriter()
        
        # Generate barcode
        code = CODE128(data, writer=writer)
        code.write(buffer, {
            'module_width': 0.2,
            'module_height': 8.0,
            'font_size': 8,
            'text_distance': 2,
            'quiet_zone': 2
        })
        
        # Load image from buffer
        buffer.seek(0)
        img = Image.open(buffer)
        img = img.resize((width, height), Image.Resampling.LANCZOS)
        
        return img
    
    def create_standard_tag(self, asset_id, device_type, hostname=None):
        """
        Create standard size asset tag (200x80mm)
        For laptops, desktops, servers
        """
        width, height = self.SIZE_LARGE
        
        # Create image
        img = Image.new('RGB', self.SIZE_LARGE, 'white')
        draw = ImageDraw.Draw(img)
        
        # Draw border
        draw.rectangle([(2, 2), (width-2, height-2)], outline='black', width=2)
        
        # Add QR code
        qr = self.generate_qr_code(asset_id, size=60)
        img.paste(qr, (10, 10))
        
        # Add text
        text_x = 80
        
        # Asset ID (large)
        draw.text((text_x, 15), asset_id, fill='black', font=self.font_large)
        
        # Device type
        draw.text((text_x, 40), device_type.upper(), fill='black', font=self.font_medium)
        
        # Hostname if provided
        if hostname:
            draw.text((text_x, 58), hostname[:15], fill='gray', font=self.font_small)
        
        return img
    
    def create_compact_tag(self, asset_id, storage_type):
        """
        Create compact asset tag (100x40mm)
        For HDDs and SSDs
        """
        width, height = self.SIZE_COMPACT
        
        # Create image
        img = Image.new('RGB', self.SIZE_COMPACT, 'white')
        draw = ImageDraw.Draw(img)
        
        # Draw border
        draw.rectangle([(1, 1), (width-1, height-1)], outline='black', width=1)
        
        # Add mini QR code
        qr = self.generate_qr_code(asset_id, size=30)
        img.paste(qr, (5, 5))
        
        # Add text (compact format)
        text_x = 40
        
        # Asset ID - split into two lines if needed
        if len(asset_id) > 12:
            # Split at dash
            parts = asset_id.split('-')
            draw.text((text_x, 5), parts[0], fill='black', font=self.font_compact)
            draw.text((text_x, 18), '-'.join(parts[1:]), fill='black', font=self.font_compact)
        else:
            draw.text((text_x, 12), asset_id, fill='black', font=self.font_compact)
        
        # Storage type indicator
        type_color = {
            'ssd': 'blue',
            'hdd': 'green',
            'usb': 'orange'
        }.get(storage_type.lower(), 'black')
        
        draw.text((text_x, 28), storage_type.upper(), fill=type_color, font=self.font_small)
        
        return img
    
    def create_mini_tag(self, asset_id):
        """
        Create mini asset tag (75x30mm)
        For very small devices
        """
        width, height = self.SIZE_MINI
        
        # Create image
        img = Image.new('RGB', self.SIZE_MINI, 'white')
        draw = ImageDraw.Draw(img)
        
        # Draw border
        draw.rectangle([(1, 1), (width-1, height-1)], outline='black', width=1)
        
        # Add tiny QR code
        qr = self.generate_qr_code(asset_id, size=25)
        img.paste(qr, (3, 3))
        
        # Add text (very compact)
        text_x = 32
        
        # Just the ID, very small
        draw.text((text_x, 10), asset_id, fill='black', font=self.font_small)
        
        return img
    
    def create_barcode_tag(self, asset_id, size='standard'):
        """
        Create barcode-style asset tag
        Alternative to QR code
        """
        if size == 'compact':
            width, height = 100, 50
        else:
            width, height = 200, 80
        
        # Create base image
        img = Image.new('RGB', (width, height), 'white')
        draw = ImageDraw.Draw(img)
        
        # Draw border
        draw.rectangle([(2, 2), (width-2, height-2)], outline='black', width=2)
        
        # Generate barcode
        try:
            barcode_img = self.generate_barcode(asset_id, width=width-20, height=40)
            # Center barcode
            barcode_x = (width - barcode_img.width) // 2
            img.paste(barcode_img, (barcode_x, 10))
        except:
            # Fallback: just text
            draw.text((10, 30), asset_id, fill='black', font=self.font_large)
        
        return img
    
    def save_tag(self, img, filepath, dpi=300):
        """
        Save tag with high DPI for printing
        """
        img.save(filepath, dpi=(dpi, dpi))
        print(f"Saved tag: {filepath}")
    
    def generate_sheet(self, tags, columns=2, spacing=10):
        """
        Generate a sheet with multiple tags for printing
        Useful for batch printing
        """
        if not tags:
            return None
        
        # Get tag size from first tag
        tag_width, tag_height = tags[0].size
        
        # Calculate sheet size
        rows = (len(tags) + columns - 1) // columns
        sheet_width = columns * tag_width + (columns + 1) * spacing
        sheet_height = rows * tag_height + (rows + 1) * spacing
        
        # Create sheet
        sheet = Image.new('RGB', (sheet_width, sheet_height), 'white')
        
        # Place tags
        for idx, tag in enumerate(tags):
            row = idx // columns
            col = idx % columns
            
            x = col * (tag_width + spacing) + spacing
            y = row * (tag_height + spacing) + spacing
            
            sheet.paste(tag, (x, y))
        
        return sheet


def demo():
    """Demo function showing all tag types"""
    generator = AssetTagGenerator()
    
    # Standard tags for devices
    laptop_tag = generator.create_standard_tag(
        "LAP-2502-0001",
        "Laptop",
        "DEVICE-WKS-001"
    )
    laptop_tag.save("demo_laptop_tag.png")
    
    # Compact tags for storage
    ssd_tag = generator.create_compact_tag("SS-2502-0042", "ssd")
    ssd_tag.save("demo_ssd_tag.png")
    
    hdd_tag = generator.create_compact_tag("HD-2502-0123", "hdd")
    hdd_tag.save("demo_hdd_tag.png")
    
    usb_tag = generator.create_compact_tag("USB-2502-0055", "usb")
    usb_tag.save("demo_usb_tag.png")
    
    # Mini tags
    mini_tag = generator.create_mini_tag("MIN-2502-9999")
    mini_tag.save("demo_mini_tag.png")
    
    # Barcode style
    barcode_tag = generator.create_barcode_tag("LAP-2502-0001")
    barcode_tag.save("demo_barcode_tag.png")
    
    # Print sheet with multiple tags
    storage_tags = [
        generator.create_compact_tag(f"SS-2502-{i:04d}", "ssd")
        for i in range(1, 9)
    ]
    sheet = generator.generate_sheet(storage_tags, columns=2)
    if sheet:
        sheet.save("demo_tag_sheet.png")
    
    print("\nDemo tags created!")
    print("Files:")
    print("  - demo_laptop_tag.png (Standard size)")
    print("  - demo_ssd_tag.png (Compact)")
    print("  - demo_hdd_tag.png (Compact)")
    print("  - demo_usb_tag.png (Compact)")
    print("  - demo_mini_tag.png (Mini)")
    print("  - demo_barcode_tag.png (Barcode style)")
    print("  - demo_tag_sheet.png (Print sheet)")


if __name__ == '__main__':
    demo()
