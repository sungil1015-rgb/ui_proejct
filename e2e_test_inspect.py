import cv2
from pathlib import Path
from server import InspectionMaster, InspectRequest # 파일 이름이 server.py인 경우

def simple_test():
    # 1. 검사기 로봇(클래스) 객체 생성
    # (data 폴더와 master 이미지가 준비되어 있어야 합니다)
    master = InspectionMaster()

    # 2. 테스트용 이미지 읽기 (OpenCV 객체로 준비)
    test_img = cv2.imread("test.jpg") 
    if test_img is None:
        print("에러: test.jpg 파일을 찾을 수 없습니다.")
        return

    # 3. 규격(Pydantic 모델)에 맞게 데이터 가공은 건너뛰고 
    # 클래스의 내부 함수를 직접 호출해서 테스트
    print("알고리즘 검사 시작...")
    
    # 가상의 요청 객체 생성 (pc_id는 실제 data 폴더 내의 폴더명과 일치해야 함)
    payload = InspectRequest(pc_id="PC_01", image="dummy_base64")
    
    # 4. 핵심 로직 실행 (base64 변환 과정 없이 직접 이미지를 넣고 싶다면)
    # 아래처럼 클래스 내부의 핵심 알고리즘 부분만 떼어 볼 수 있습니다.
    try:
        # 이 코드는 서버 구동 없이 '로봇'만 따로 떼서 일 시키는 것과 같습니다.
        # 실제로는 payload.image를 디코딩해야 하므로, 
        # 실험을 위해 내부의 _inspect_single_serial을 직접 호출해볼 수도 있습니다.
        
        # 예시: 특정 시리얼 폴더 하나에 대해 테스트
        serial_dir = Path("data/PC_01/serial_01")
        result = master._inspect_single_serial(serial_dir, test_img, "PC_01")
        
        print(f"검사 완료! 시리얼: {result['serial_id']}")
        print(f"평균 유사도 점수: {result['avg_score']:.4f}")
        print(f"결과 이미지 저장 경로: {result['result_image_path']}")

    except Exception as e:
        print(f"테스트 중 오류 발생: {e}")

if __name__ == "__main__":
    simple_test()