<?php

namespace App\Models\Labels\Sheets\Avery;

// Layout for an Avery 5267 or 8927 label with QR code and three fields to the right:
//
//  +--------+
//  |        | Field 1
//  |   QR   | Field 2
//  |        | Field 3
//  +--------+

class _5267_B extends _5267
{
    private const BARCODE_SIZE   =   0.175;
    private const BARCODE_MARGIN =   0.020;
    private const FIELD_SIZE     =   0.150;
    private const FIELD_MARGIN   =   0.012;

    public function getUnit() { return 'in'; }

    public function getLabelMarginTop()    { return 0.02; }
    public function getLabelMarginBottom() { return 0.02; }
    public function getLabelMarginLeft()   { return 0.04; }
    public function getLabelMarginRight()  { return 0.04; }

    public function getSupportAssetTag()  { return false; }
    public function getSupport1DBarcode() { return false; }
    public function getSupport2DBarcode() { return true; }
    public function getSupportFields()    { return 3; }
    public function getSupportLogo()      { return false; }
    public function getSupportTitle()     { return false; }

    public function preparePDF($pdf) {}

    public function write($pdf, $record) {
        $pa = $this->getLabelPrintableArea();

        $usableWidth = $pa->w;
        $currentX = $pa->x1;
        $currentY = $pa->y1;

        $barcodeSize = $pa->h;

        if ($record->has('barcode2d')) {
            static::write2DBarcode(
                $pdf, $record->get('barcode2d')->content, $record->get('barcode2d')->type,
                $pa->x1, $pa->y1,
                $barcodeSize, $barcodeSize
            );
            $currentX += $barcodeSize + self::BARCODE_MARGIN;
            $usableWidth -= $barcodeSize + self::BARCODE_MARGIN;
        }

        foreach ($record->get('fields') as $field) {
            static::writeText(
                $pdf, $field['value'],
                $currentX, $currentY,
                'freemono', 'B', self::FIELD_SIZE, 'L',
                $usableWidth, self::FIELD_SIZE, true
            );
            $currentY += self::FIELD_SIZE + self::FIELD_MARGIN;
        }
    }
}

?>
