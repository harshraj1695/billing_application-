import svgwrite
import barcode
from barcode.writer import SVGWriter
import os
import shutil
import sys
import textwrap
from json import loads
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

RESOURCE_DIR = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else RESOURCE_DIR
runtime_config_path = APP_DIR / 'config.json'
if not runtime_config_path.exists():
    runtime_config_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(RESOURCE_DIR / 'config.json', runtime_config_path)
config_data = loads(runtime_config_path.read_text())
store_logo_path = RESOURCE_DIR / 'assets' / 'lalitaandsons.png'
radhekrina_image_path = RESOURCE_DIR / 'images' / 'radhekrina.png'


def escpos_raster_image(image_path, max_width=384, max_height=160):
    """Return ESC/POS raster commands for an image, sized for receipt paper."""
    with Image.open(image_path) as source:
        image = Image.new('RGBA', source.size, 'white')
        image.alpha_composite(source.convert('RGBA'))
        image = image.convert('L')

    scale = min(max_width / image.width, max_height / image.height, 1)
    if scale < 1:
        image = image.resize(
            (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
            Image.LANCZOS,
        )

    width, height = image.size
    bytes_per_row = (width + 7) // 8
    raster = bytearray(bytes_per_row * height)
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            if pixels[x, y] < 128:
                raster[y * bytes_per_row + x // 8] |= 0x80 >> (x % 8)

    return [
        b'\x1B\x61\x01',
        b'\x1D\x76\x30\x00'
        + bytes((bytes_per_row & 0xFF, bytes_per_row >> 8, height & 0xFF, height >> 8))
        + bytes(raster),
        b'\n',
        b'\x1B\x61\x00',
    ]

class StickerGenerator:

    def __init__(self, products, svg_file_path):
        self.products = products
        self.svg_file_path = svg_file_path
        self.sticker_width, self.sticker_height = 75, 50
        self.dflt_font_size, self.mrp_font_size, self.discount_font_size = 14, 18, 22
        self.barcode_max_len = config_data['billing']['barcode_max_len']
        self.temp_fold = APP_DIR / 'temp'
        os.makedirs(self.temp_fold, exist_ok=True)

    def generate_stickers(self):

        gap_width_mm = 0  # 5mm gap
        canvas_height_mm = (self.sticker_height + gap_width_mm) * len(self.products) - gap_width_mm
        canvas_width_mm = self.sticker_width

        # Create an SVG drawing for the canvas
        canvas = svgwrite.Drawing(self.svg_file_path, profile='tiny', size=(f'{canvas_width_mm}mm', f'{canvas_height_mm}mm'))

        # Generate and arrange stickers on the canvas
        y_offset = 0

        for product in self.products:
            product_id = str(product['product_id']).zfill(self.barcode_max_len)
            product_name = product['product_name']
            product_size = product['product_size']
            product_color = product['product_color']
            mrp = product['product_mrp']
            discounted_price = round(product['product_discounted_price'], 2)

            logo = canvas.image(str(store_logo_path), size=('30mm', f'{self.sticker_height - 25}mm'), insert=('3mm', f'{y_offset}mm'), preserveAspectRatio='xMidYMid meet')
            logo.set_desc('Company Logo')
            canvas.add(logo)

            canvas.add(canvas.text(f"Item:" , insert=('35mm', f'{y_offset + 6}mm'), font_size=self.dflt_font_size, fill='black'))
            canvas.add(canvas.text(f"{product_name}", insert=('45mm', f'{y_offset + 6}mm'), font_size=self.dflt_font_size, fill='black', font_weight='bold'))

            canvas.add(canvas.text(f"Size:", insert=('35mm', f'{y_offset + 10}mm'), font_size=self.dflt_font_size, fill='black'))
            canvas.add(canvas.text(f"{product_size}", insert=('45mm', f'{y_offset + 10}mm'), font_size=self.dflt_font_size, fill='black', font_weight='bold'))

            canvas.add(canvas.text(f"Color:", insert=('35mm', f'{y_offset + 14}mm'), font_size=self.dflt_font_size, fill='black'))
            canvas.add(canvas.text(f"{product_color}", insert=('45mm', f'{y_offset + 14}mm'), font_size=self.dflt_font_size, fill='black', font_weight='bold'))

            mrp, discounted_price = round(float(mrp), 2), round(float(discounted_price), 2)
            canvas.add(canvas.text(f"MRP:", insert=('35mm', f'{y_offset + 21.5}mm'), font_size=self.dflt_font_size, fill='black'))
            canvas.add(canvas.text(f"₹ {mrp}", insert=('45mm', f'{y_offset + 21.5}mm'), font_size=self.mrp_font_size, fill='black', font_weight='bold'))

            canvas.add(canvas.text(f"Discount Price:", insert=('6.5mm', f'{y_offset + 29}mm'), font_size=self.dflt_font_size, fill='black'))
            canvas.add(canvas.text(f"₹ {discounted_price}/- Only", insert=('34mm', f'{y_offset + 29}mm'), font_size=self.discount_font_size, fill='black', font_weight='bold'))
            canvas.add(canvas.text(f"(Incl of all taxes)", insert=('32mm', f'{y_offset + 33}mm'), font_size=self.dflt_font_size, fill='black'))

            render_options = {
                'module_width': 0.4,
                'module_height': 10.0,
                'font_size': 12,
                }
            barcode.generate('code128', product_id, writer=SVGWriter(), output=str(self.temp_fold / f'{product_id}_barcode'), writer_options=render_options)
            # Add the barcode image below the company name
            barcode_image = canvas.image(str(self.temp_fold / f'{product_id}_barcode.svg'), insert=('10mm', f'{y_offset + self.sticker_height - 15}mm'), size=(f'{self.sticker_width - 20}mm', '15mm'))
            barcode_image.set_desc('Barcode')
            canvas.add(barcode_image)

            y_offset += self.sticker_height + gap_width_mm

        canvas.save()

class EscPosCmdGenerator:

    def __init__(self, bill_no, emp_id, table_data, discount, payment_details):
        self.bill_no = bill_no
        self.emp_id = emp_id
        self.table_data = table_data        # list of lists -- [id, desc, qty, price, total, gst] where price is discounted price
        self.discount = discount
        self.payment_details = payment_details  # tuple of strings mode-amount

    def generate_esc_pos_cmds(self):

        store_details = config_data['store']

        col1_end_pos = 10
        col2_end_pos = 22
        col3_end_pos = 31
        col4_end_pos = 41

        # store details
        esc_pos_commands = [
            b'\x1B\x40',                  # Initialize printer
            b'\x1B\x61\x01',              # Center align text
            b'\x1B\x21\x30',              # Double height and width text
            store_details['store_name'].encode('utf-8'),
            b'\n'
            b'\x1B\x21\x00',              # Reset to normal text size
            store_details['store_address1'].encode('utf-8'),
            b'\n',
            store_details['store_address2'].encode('utf-8'),
            b'\n',
            f'Phone: {store_details["store_phone"]}'.encode('utf-8'),
            b'\n',
            f'GSTIN: {store_details["store_gstin"]}'.encode('utf-8'),
            b'\n',
        ]
        esc_pos_commands += escpos_raster_image(radhekrina_image_path)
        esc_pos_commands += [
            b'\x1B\x61\x00',
            b'------------------------------------------------\n',
            b'\x1B\x61\x01',              # Center align text
            b'\x1B\x45\x01',              # Bold text
            b'\x1B\x21\x30',              # Double height and width text
            b'TAX INVOICE\n',
            b'\x1B\x21\x00',              # Reset to normal text size
            b'\x1B\x45\x00',              # Normal text
            b'\x1B\x61\x00',              # Left align text
            b'------------------------------------------------\n',

            f' Bill No: {self.bill_no} Date: {datetime.now().strftime("%d/%m/%Y-%H:%M:%S")}\n'.encode('utf-8'),
            f' Cashier: {self.emp_id}\n'.encode('utf-8'),
            b'\x1B\x45\x01'
            b'+----------------------------------------------+\n',  # Top border of the table
            b'| id                  Qty     Price      Total |\n',  # Header row
            b'|----------------------------------------------|\n',  # Header row separator
            b'\x1B\x45\x00'                                         # Normal text
            b'\x1B\x61\x00'           # Left align text
        ]


        def add_row_to_commands(id, desc, qty, price, total, gst, commands):
            # Create a format string for the row
            id, qty, price, total = str(id), str(qty), str(round(float(price), 2)), str(round(float(total), 2))

            price = f'{float(price):.2e}' if len(price) > 8 else price
            total = f'{float(total):.2e}' if len(total) > 8 else total

            id = str(id).zfill(7)

            row_format = f'| {id:<{col1_end_pos}} {qty:>{col2_end_pos - col1_end_pos}} {price:>{col3_end_pos - col2_end_pos}} {total:>{col4_end_pos - col3_end_pos}} |\n'
            
            # Append the formatted row to the existing commands
            commands.append(row_format.encode('utf-8'))
            #append description
            commands.append(f'  {desc}\n'.encode('utf-8'))
            taxable_amt = round(float(total)/(1 + gst/100), 2)
            taxable_amt = f'{taxable_amt:.2e}' if len(str(taxable_amt)) > 8 else taxable_amt
            commands.append(f'  Taxable Value: {taxable_amt} CGST@{round(gst/2, 2)}% SGST@{round(gst/2, 2)}%\n'.encode('utf-8'))
            commands.append(b'|----------------------------------------------|\n')
            return commands

        # Add each row of data to the existing commands
        total_items_org, total_qty_org, total_price_org = 0, 0, 0.0
        gst_details = {}
        for row in self.table_data:
            esc_pos_commands = add_row_to_commands(row[0], row[1], row[2], row[3], row[4], row[5], esc_pos_commands)
            total_items_org += 1
            total_qty_org += row[2]
            total_price_org += row[4]
            taxable_amt = round(float(row[4])/(1 + row[5]/100), 2)
            if row[5] not in gst_details:
                gst_details[row[5]] = {'taxable_amt': taxable_amt, 'cgst': round(taxable_amt*row[5]/200, 2), 'sgst': round(taxable_amt*row[5]/200, 2), 'total': round(row[4], 2)}
            else:
                gst_details[row[5]]['taxable_amt'] += taxable_amt
                gst_details[row[5]]['cgst'] += round(taxable_amt*row[5]/200, 2)
                gst_details[row[5]]['sgst'] += round(taxable_amt*row[5]/200, 2)
                gst_details[row[5]]['total'] += round(row[4], 2)

        total_items, total_qty = int(total_items_org), int(total_qty_org)
        total_price = f'{total_price_org:.2e}' if len(str(total_price_org)) > 8 else round(total_price_org, 2)
        net_total_diplay = int(total_price_org - self.discount)

        esc_pos_commands += (
            f'  Discount: {round(self.discount, 2)}\n'.encode('utf-8'),
            b'|----------------------------------------------|\n'
            #bold text
            b'\x1B\x45\x01',
            # increase font size
            b'\x1B\x21\x12',
            # align center
            b'\x1B\x61\x01',
            b'  Items: ' + str(total_items).encode('utf-8') + b'    Qty: ' + str(total_qty).encode('utf-8') + b'    NetTotal: ' + str(net_total_diplay).encode('utf-8') + b'\n',
            # align left
            b'\x1B\x61\x00',
            # normal font size
            b'\x1B\x21\x00',
            b'\x1B\x45\x01',
            b'+----------------------------------------------+\n\n',  # Bottom border of the table
            b'<-------------GST Breakup Details-------------->\n',
            b'+----------------------------------------------+\n',
            b'| Taxable Value      CGST      SGST      Total |\n',
            b'|----------------------------------------------|\n',
            b'\x1B\x45\x00'
        )

            
        total_taxable_amt_org, total_cgst_org, total_sgst_org = 0.0, 0.0, 0.0
        for gst, gst_detail in gst_details.items():
            taxable_amt = round(gst_detail['taxable_amt'], 2)
            cgst = round(float(gst_detail['cgst']), 2)
            sgst = round(float(gst_detail['sgst']), 2)
            total = round(float(gst_detail['total']), 2)
            total_taxable_amt_org += taxable_amt
            total_cgst_org += cgst
            total_sgst_org += sgst
            taxable_amt = f'{taxable_amt:.2e}' if len(str(taxable_amt)) > 8 else taxable_amt
            cgst = f'{cgst:.2e}' if len(str(cgst)) > 8 else cgst
            sgst = f'{sgst:.2e}' if len(str(sgst)) > 8 else sgst
            total = f'{total:.2e}' if len(str(total)) > 8 else total
            esc_pos_commands.append(f'  CGST@{round(gst/2, 2)}% SGST@{round(gst/2, 2)}%\n'.encode('utf-8'))
            cmd = f'| {taxable_amt:<{col1_end_pos}} {cgst:>{col2_end_pos - col1_end_pos}} {sgst:>{col3_end_pos - col2_end_pos}} {total:>{col4_end_pos - col3_end_pos}} |\n'
            esc_pos_commands.append(cmd.encode('utf-8'))
            esc_pos_commands.append(b'|----------------------------------------------|\n')

        total_taxable_amt = f'{total_taxable_amt_org:.2e}' if len(str(round(total_taxable_amt_org, 2))) > 8 else round(total_taxable_amt_org, 2)
        total_cgst = f'{total_cgst_org:.2e}' if len(str(total_cgst_org)) > 8 else round(total_cgst_org, 2)
        total_sgst = f'{total_sgst_org:.2e}' if len(str(total_sgst_org)) > 8 else round(total_sgst_org, 2)

        total_tax_cmd = f'| {total_taxable_amt:<{col1_end_pos}} {total_cgst:>{col2_end_pos - col1_end_pos}} {total_sgst:>{col3_end_pos - col2_end_pos}} {total_price:>{col4_end_pos - col3_end_pos}} |\n'
        esc_pos_commands += (
            b'\x1B\x45\x01',
            b'\x1B\x21\x08',
            total_tax_cmd.encode('utf-8'),
            b'\x1B\x45\x00',
            b'+----------------------------------------------+\n',
        )

        # Payment details
        payment_cmd = ''
        for payment_detail in self.payment_details:
            mode, amount = payment_detail.split('-')[0], round(float(payment_detail.split('-')[1]), 2)
            payment_cmd += f'  {mode:<{col1_end_pos}} {amount:>{col4_end_pos - col1_end_pos}}\n'
        esc_pos_commands += (
            b'\n',
            b'------------------------------------------------\n',
            b'\x1B\x61\x01',              # Center align text
            b'\x1B\x45\x01',              # Bold text
            f'Payment Details\n'.encode('utf-8'),
            b'------------------------------------------------\n',
            b'\x1B\x45\x00',              # Normal text
            b'\x1B\x61\x00',              # Left align text
            payment_cmd.encode('utf-8'),
            b'------------------------------------------------\n\n',
            b'\x1B\x61\x01',              # Center align text
            b'\x1B\x45\x01',              # Bold text
            f'Thank you for your business!\n'.encode('utf-8'),
            b'\x1B\x45\x00',              # Normal text
            b'\x1B\x61\x00',              # Left align text
            b'\x1D\x56\x41\x10',          # Cut paper (partial cut)



        )
        #     b'\n',
        #     b'Thank you for your business!\n',
        #     b'\x1B\x61\x00',              # Left align text
        #     b'\x1D\x56\x41\x10',          # Cut paper (partial cut)
        # )

        return esc_pos_commands


class BillPdfGenerator:
    """Create a readable PDF copy of a thermal receipt."""

    def __init__(self, bill_no, emp_id, table_data, discount, payment_details):
        self.bill_no = bill_no
        self.emp_id = emp_id
        self.table_data = table_data
        self.discount = discount
        self.payment_details = payment_details

    @staticmethod
    def _font(size, bold=False):
        candidates = (
            ('DejaVuSans-Bold.ttf', 'arialbd.ttf')
            if bold else ('DejaVuSans.ttf', 'arial.ttf')
        )
        for candidate in candidates:
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
        return ImageFont.load_default()

    def save(self, output_path):
        width, margin = 576, 28
        line_height = 24
        estimated_height = 600 + sum(58 + 22 * max(1, len(textwrap.wrap(str(row[1]), width=38))) for row in self.table_data)
        image = Image.new('RGB', (width, estimated_height), 'white')
        draw = ImageDraw.Draw(image)
        regular = self._font(18)
        small = self._font(15)
        bold = self._font(20, bold=True)
        heading = self._font(28, bold=True)
        y = margin

        with Image.open(radhekrina_image_path) as deity:
            deity = deity.convert('RGBA')
            deity.thumbnail((100, 100), Image.LANCZOS)
            image.paste(deity, ((width - deity.width) // 2, y), deity)
            y += deity.height + 12

        store = config_data['store']
        for text, font in (
            (store['store_name'], heading),
            (store['store_address1'], small),
            (store['store_address2'], small),
            (f"Phone: {store['store_phone']}  |  GSTIN: {store['store_gstin']}", small),
        ):
            text_width = draw.textbbox((0, 0), text, font=font)[2]
            draw.text(((width - text_width) // 2, y), text, font=font, fill='black')
            y += line_height if font is small else 36

        draw.line((margin, y, width - margin, y), fill='black', width=2)
        y += 12
        draw.text((margin, y), 'TAX INVOICE', font=bold, fill='black')
        y += 30
        draw.text((margin, y), f'Bill No: {self.bill_no}', font=small, fill='black')
        draw.text((width - 215, y), datetime.now().strftime('%d/%m/%Y %H:%M'), font=small, fill='black')
        y += 23
        draw.text((margin, y), f'Cashier: {self.emp_id}', font=small, fill='black')
        y += 32

        draw.rectangle((margin, y, width - margin, y + 28), fill=(112, 78, 25))
        draw.text((margin + 6, y + 4), 'Item', font=small, fill='white')
        draw.text((390, y + 4), 'Qty', font=small, fill='white')
        draw.text((455, y + 4), 'Amount', font=small, fill='white')
        y += 36

        total_quantity = 0
        total_amount = 0.0
        for product_id, description, quantity, _price, amount, _gst in self.table_data:
            description_lines = textwrap.wrap(f'{product_id}: {description}', width=38) or ['']
            for line in description_lines:
                draw.text((margin, y), line, font=small, fill='black')
                y += 20
            draw.text((395, y - 20), str(quantity), font=small, fill='black')
            draw.text((450, y - 20), f'Rs. {float(amount):.2f}', font=small, fill='black')
            total_quantity += int(quantity)
            total_amount += float(amount)
            y += 7
            draw.line((margin, y, width - margin, y), fill=(210, 210, 210))
            y += 10

        net_total = total_amount - float(self.discount)
        for label, value, font in (
            ('Items / Quantity', f'{len(self.table_data)} / {total_quantity}', regular),
            ('Discount', f'Rs. {float(self.discount):.2f}', regular),
            ('Net Total', f'Rs. {net_total:.2f}', bold),
        ):
            draw.text((margin, y), label, font=font, fill='black')
            value_width = draw.textbbox((0, 0), value, font=font)[2]
            draw.text((width - margin - value_width, y), value, font=font, fill='black')
            y += 30

        y += 4
        draw.line((margin, y, width - margin, y), fill='black', width=2)
        y += 12
        draw.text((margin, y), 'Payment Details', font=bold, fill='black')
        y += 28
        for payment in self.payment_details:
            mode, amount = payment.split('-', 1)
            draw.text((margin, y), mode, font=regular, fill='black')
            amount_text = f'Rs. {float(amount):.2f}'
            amount_width = draw.textbbox((0, 0), amount_text, font=regular)[2]
            draw.text((width - margin - amount_width, y), amount_text, font=regular, fill='black')
            y += 26

        y += 10
        thanks = 'Thank you for your business!'
        thanks_width = draw.textbbox((0, 0), thanks, font=bold)[2]
        draw.text(((width - thanks_width) // 2, y), thanks, font=bold, fill=(112, 78, 25))
        image.crop((0, 0, width, y + 45)).save(output_path, 'PDF', resolution=150.0)
