import sys
from PIL import Image, ImageDraw, ImageFont

def test():
    img = Image.new("RGB", (1920, 1080), "#0B132B")
    draw = ImageDraw.Draw(img)
    font_bold = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 48)
    draw.text((100, 100), "Proofbox | Vultr Hackathon Walkthrough", fill="#38BDF8", font=font_bold)
    img.save("brag-output/test_frame.png")
    print("Frame saved successfully!")

if __name__ == "__main__":
    test()

